# Copyright 2019 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
r"""Promote an expression to be a child of its grandparent.

Promote is part of the standard flattening of data, promote_and_broadcast,
which takes structured data and flattens it. By directly accessing promote,
one can perform simpler operations.

For example, suppose an expr represents:


+
|
+-session*   (stars indicate repeated)
     |
     +-event*
         |
         +-val*-int64

session: {
  event: {
    val: 111
  }
  event: {
    val: 121
    val: 122
  }
}

session: {
  event: {
    val: 10
    val: 7
  }
  event: {
    val: 1
  }
}

promote.promote(expr, path.Path(["session", "event", "val"]), nval) produces:

+
|
+-session*   (stars indicate repeated)
     |
     +-event*
     |    |
     |    +-val*-int64
     |
     +-nval*-int64

session: {
  event: {
    val: 111
  }
  event: {
    val: 121
    val: 122
  }
  nval: 111
  nval: 121
  nval: 122
}

session: {
  event: {
    val: 10
    val: 7
  }
  event: {
    val: 1
  }
  nval: 10
  nval: 7
  nval: 1
}


TODO(martinz): promote structures in addition to leaves.
"""

from __future__ import absolute_import
from __future__ import division

from __future__ import print_function

from struct2tensor import calculate_options
from struct2tensor import expression
from struct2tensor import expression_add
from struct2tensor import path
from struct2tensor import prensor
import tensorflow as tf
from typing import Optional, Sequence, Tuple

from tensorflow_metadata.proto.v0 import schema_pb2


class PromoteExpression(expression.Leaf):
  """A promoted leaf."""

  def __init__(self, origin,
               origin_parent):

    super(PromoteExpression, self).__init__(
        origin.is_repeated or origin_parent.is_repeated,
        origin.type,
        schema_feature=_get_promote_schema_feature(
            origin.schema_feature, origin_parent.schema_feature))
    self._origin = origin
    self._origin_parent = origin_parent
    if self.type is None:
      raise ValueError("Can only promote a field")
    if self._origin_parent.type is not None:
      raise ValueError("origin_parent cannot be a field")

  def get_source_expressions(self):
    return [self._origin, self._origin_parent]

  def calculate(self, sources,
                destinations,
                options):
    [origin_value, origin_parent_value] = sources
    if not isinstance(origin_value, prensor.LeafNodeTensor):
      raise ValueError("origin_value must be a leaf")
    if not isinstance(origin_parent_value, prensor.ChildNodeTensor):
      raise ValueError("origin_parent_value must be a child node")
    parent_to_grandparent_index = origin_parent_value.parent_index
    new_parent_index = tf.gather(parent_to_grandparent_index,
                                 origin_value.parent_index)
    return prensor.LeafNodeTensor(new_parent_index, origin_value.values,
                                  self.is_repeated)

  def calculation_is_identity(self):
    return False

  def calculation_equal(self, expr):
    return isinstance(expr, PromoteExpression)


def _lifecycle_stage_number(a):
  """Return a number indicating the quality of the lifecycle stage.

  When there is more than one input field, the minimum lifecycle stage could be
  used.

  Args:
    a: an Optional[LifecycleStage]
  Returns: an integer
  """
  stages = [
      schema_pb2.LifecycleStage.DEPRECATED, schema_pb2.LifecycleStage.PLANNED,
      schema_pb2.LifecycleStage.ALPHA, schema_pb2.LifecycleStage.DEBUG_ONLY,
      None, schema_pb2.LifecycleStage.UNKNOWN_STAGE,
      schema_pb2.LifecycleStage.BETA, schema_pb2.LifecycleStage.PRODUCTION
  ]
  return stages.index(a)


def _min_lifecycle_stage(a, b):
  """Get the minimum lifecycle stage.

  Args:
    a: an Optional[LifecycleStage]
    b: an Optional[LifecycleStage]

  Returns:
    the minimal lifecycle stage.
  """
  if _lifecycle_stage_number(b) < _lifecycle_stage_number(a):
    return b
  return a


def _feature_is_dense(feature):
  return (feature.presence.min_fraction == 1.0 and
          feature.value_count.HasField("min") and
          feature.value_count.HasField("max") and
          feature.value_count.min == feature.value_count.max)


def _copy_domain_info(origin, dest):
  """Copy the domain info."""
  one_of_field_name = origin.WhichOneof("domain_info")
  if one_of_field_name is None:
    return

  origin_field = getattr(origin, one_of_field_name)

  field_descriptor = origin.DESCRIPTOR.fields_by_name.get(one_of_field_name)
  if field_descriptor is None or field_descriptor.message_type is None:
    setattr(dest, one_of_field_name, origin_field)
  else:
    dest_field = getattr(dest, one_of_field_name)
    dest_field.CopyFrom(origin_field)


def _get_promote_schema_feature(original,
                                parent
                               ):
  """Generate the schema feature for the field resulting from promote.

  Note that promote results in the exact same number of values.

  Note that min_count is never propagated.

  Args:
    original: the original feature
    parent: the parent feature

  Returns:
    the schema of the new field.
  """
  if original is None or parent is None:
    return None
  result = schema_pb2.Feature()
  result.lifecycle_stage = _min_lifecycle_stage(original.lifecycle_stage,
                                                parent.lifecycle_stage)
  result.type = original.type
  if original.HasField("distribution_constraints"):
    result.distribution_constraints.CopyFrom(original.distribution_constraints)
  _copy_domain_info(original, result)

  if _feature_is_dense(parent):
    parent_size = parent.value_count.min
    if original.value_count.HasField("min"):
      result.value_count.min = parent_size * original.value_count.min
    if original.value_count.HasField("max"):
      result.value_count.max = parent_size * original.value_count.max
    if original.presence.HasField("min_fraction"):
      if original.presence.min_fraction == 1:
        result.presence.min_fraction = 1
      else:
        result.presence.min_fraction = (
            original.presence.min_fraction / parent_size)
    if original.presence.HasField("min_count"):
      # If the parent is dense then the count can
      # be reduced by the number of children.
      # E.g. {{"a"},{"b"}},{{"c"},{"d"}},{{"e"},{"f"}}
      # with a count of 6, with a parent size of 2 becomes:
      # can become {"a","b"}, {"c", "d"}, {"e", "f"}
      # which has a count of 3.
      result.presence.min_count = original.presence.min_count // parent_size
  return result


def _promote_impl(root, p,
                  new_field_name
                 ):
  if len(p) < 2:
    raise ValueError("Cannot do a promotion beyond the root: {}".format(str(p)))
  parent_path = p.get_parent()
  grandparent_path = parent_path.get_parent()
  new_path = grandparent_path.get_child(new_field_name)
  return expression_add.add_paths(
      root, {
          new_path:
              PromoteExpression(
                  root.get_descendant_or_error(p),
                  root.get_descendant_or_error(parent_path))
      }), new_path


def promote_anonymous(root,
                      p):
  """Promote a path to be a new anonymous child of its grandparent."""
  return _promote_impl(root, p, path.get_anonymous_field())


def promote(root, p,
            new_field_name):
  """Promote a path to be a child of its grandparent, and give it a name."""
  return _promote_impl(root, p, new_field_name)[0]
