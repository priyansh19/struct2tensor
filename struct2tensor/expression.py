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
"""An expression represents the calculation of a prensor object.

Like a prensor, an expression has a tree structure, where a child of an
expression is also an expression. From each expression one can calculate a
NodeTensor (for a reference implementation, see
expression_test_util.calculate_value_slowly). Expressions also have properties
type and is_repeated that identify the dtype and repeeatedness of the resulting
NodeTensor.

Unlike prensors, an expression may have an infinite number of children. For
example, a node representing an "Any" proto has an optional child for each
proto message type. The operations get_known_children() and
get_known_descendants() return the "known" children. In general, it is best
to call project.project() to get the desired fields before calling
get_known_children().


"""

from __future__ import absolute_import
from __future__ import division

from __future__ import print_function

import abc
from struct2tensor import calculate_options
from struct2tensor import path
from struct2tensor import prensor
import tensorflow as tf
from typing import Callable, FrozenSet, List, Mapping, Optional, Sequence, Union

from tensorflow.python.util.lazy_loader import LazyLoader  # pylint: disable=g-direct-tensorflow-import
from tensorflow_metadata.proto.v0 import schema_pb2

# The purpose of this type is to make it easy to write down paths as literals.
# If we made it Text instead of str, then it wouldn't be easy anymore.
CoercableToPath = path.CoercableToPath

# The LazyLoader is used to avoid a loop. All of the following packages depend
# upon this one.
# Similar to:
# from struct2tensor.expression_impl import promote
promote = LazyLoader("promote", globals(),
                     "struct2tensor.expression_impl.promote")

broadcast_module = LazyLoader("broadcast", globals(),
                              "struct2tensor.expression_impl.broadcast")

promote_and_broadcast = LazyLoader(
    "broadcast", globals(), "struct2tensor.expression_impl"
    ".promote_and_broadcast")

map_values = LazyLoader("map_values", globals(),
                        "struct2tensor.expression_impl.map_values")

project = LazyLoader("project", globals(),
                     "struct2tensor.expression_impl.project")

size = LazyLoader("size", globals(), "struct2tensor.expression_impl.size")

reroot = LazyLoader("reroot", globals(), "struct2tensor.expression_impl.reroot")

map_prensor = LazyLoader("map_prensor", globals(),
                         "struct2tensor.expression_impl.map_prensor")

apply_schema = LazyLoader("apply_schema", globals(),
                          "struct2tensor.expression_impl.apply_schema")

slice_expression = LazyLoader("slice_expression", globals(),
                              "struct2tensor.expression_impl.slice_expression")

# Type for limit arguments to slice (begin, end).
# Union[int, tf.Tensor, tf.Variable]
IndexValue = Union[int, tf.Tensor, tf.Variable]  # pylint: disable=invalid-name


class Expression(object):
  """An expression represents the calculation of a prensor object."""

  __metaclass__ = abc.ABCMeta

  def __init__(self,
               is_repeated,
               my_type,
               schema_feature = None):
    """Initialize an expression.

    Args:
      is_repeated: if the expression is repeated.
      my_type: the DType of a field, or None for an internal node.
      schema_feature: the local schema (StructDomain information should not be
        present).
    """
    self._is_repeated = is_repeated
    self._type = my_type
    self._child_cache = {}
    self._schema_feature = schema_feature

  @property
  def is_repeated(self):
    """True iff the same parent value can have multiple children values."""
    return self._is_repeated

  @property
  def type(self):
    """dtype of the expression, or None if not a leaf expression."""
    return self._type

  @property
  def is_leaf(self):
    """True iff the node tensor is a LeafNodeTensor."""
    return self.type is not None

  @property
  def schema_feature(self):
    """Return the schema of the field."""
    return self._schema_feature

  @abc.abstractmethod
  def get_source_expressions(self):
    """Gets the sources of this expression.

    The node tensors of the source expressions must be sufficient to
    calculate the node tensor of this expression
    (see calculate and calculate_value_slowly).

    Returns:
      The sources of this expression.
    """
    raise NotImplementedError()

  @abc.abstractmethod
  def calculate(self, source_tensors,
                destinations,
                options):
    """Calculates the node tensor of the expression.

    The node tensor must be a function of the properties of the expression
    and the node tensors of the expressions from get_source_expressions().

    If is_leaf, then calculate must return a LeafNodeTensor.
    Otherwise, it must return a ChildNodeTensor or RootNodeTensor.

    If calculate_is_identity is true, then this must return source_tensors[0].

    Sometimes, for operations such as parsing the proto, calculate will return
    additional information. For example, calculate() for the root of the
    proto expression also parses out the tensors required to calculate the
    tensors of the children. This is why destinations are required.

    For a reference use, see calculate_value_slowly(...) below.

    Args:
      source_tensors: The node tensors of the expressions in
        get_source_expressions().
      destinations: The expressions that will use the output of this method.
      options: Options for the calculation.

    Returns:
      A NodeTensor representing the output of this expression.
    """
    raise NotImplementedError()

  @abc.abstractmethod
  def calculation_is_identity(self):
    """True iff the self.calculate is the identity.

    There is exactly one source, and the output of self.calculate(...) is the
    node tensor of this source.
    """
    raise NotImplementedError()

  @abc.abstractmethod
  def calculation_equal(self, expression):
    """self.calculate is equal to another expression.calculate.

    Given the same source node tensors, self.calculate(...) and
    expression.calculate(...) will have the same result.

    Note that this does not check that the source expressions of the two
    expressions are the same. Therefore, two operations can have the same
    calculation, but not the same output, because their sources are different.
    For example, if a.calculation_is_identity() is True and
    b.calculation_is_identity() is True, then a.calculation_equal(b) is True.
    However, unless a and b have the same source, the expressions themselves are
    not equal.

    Args:
      expression: The expression to compare to.
    """
    raise NotImplementedError()

  @abc.abstractmethod
  def _get_child_impl(self, field_name):
    """Implementation of getting a named child in a subclass.

    This is called and cached inside get_child().

    Args:
      field_name: the field accessed.

    Returns:
      The expression of the field, or None if the field does not exist.
    """
    raise NotImplementedError()

  @abc.abstractmethod
  def known_field_names(self):
    """Returns known field names of the expression.

    TODO(martinz): implement set_field and project.
    Known field names of a parsed proto correspond to the fields declared in
    the message. Examples of "unknown" fields are extensions and explicit casts
    in an any field. The only way to know if an unknown field "(foo.bar)" is
    present in an expression expr is to call (expr["(foo.bar)"] is not None).

    Notice that simply accessing a field does not make it "known". However,
    setting a field (or setting a descendant of a field) will make it known.

    project(...) returns an expression where the known field names are the only
    field names. In general, if you want to depend upon known_field_names
    (e.g., if you want to compile a expression), then the best approach is to
    project() the expression first.

    Returns:
      An immutable set of field names.
    """

  def get_child(self, field_name):
    """Gets a named child."""
    if field_name in self._child_cache:
      return self._child_cache[field_name]
    result = self._get_child_impl(field_name)
    self._child_cache[field_name] = result
    return result

  def get_child_or_error(self, field_name):
    """Gets a named child."""
    result = self.get_child(field_name)
    if result is None:
      raise KeyError("No such field: {}".format(field_name))
    return result

  def get_descendant(self, p):
    """Finds the descendant at the path."""
    result = self
    for field_name in p.field_list:
      result = result.get_child(field_name)
      if result is None:
        return None
    return result

  def get_descendant_or_error(self, p):
    """Finds the descendant at the path."""
    result = self.get_descendant(p)
    if result is None:
      raise ValueError("Missing path: {} in {}".format(
          str(p), self.schema_string(limit=20)))
    return result

  def get_known_children(self):
    known_field_names = self.known_field_names()
    result = {}
    for name in known_field_names:
      result[name] = self.get_child_or_error(name)
    return result

  def get_known_descendants(self):
    # Rename get_known_descendants
    """Gets a mapping from known paths to subexpressions.

    The difference between this and get_descendants in Prensor is that
    all paths in a Prensor are known, in the sense that all


    Returns:
      A mapping from paths (relative to the root of the subexpression) to
      expressions.
    """
    known_subexpressions = {
        k: v.get_known_descendants()
        for k, v in self.get_known_children().items()
    }
    result = {}
    for field_name, subexpression in known_subexpressions.items():
      subexpression_path = path.Path([field_name])
      for p, expr in subexpression.items():
        result[subexpression_path.concat(p)] = expr
    result[path.Path([])] = self
    return result

  def _schema_string_helper(self, field_name,
                            limit):  # pylint: disable=g-ambiguous-str-annotation
    """Helper for schema_string."""
    repeated_as_string = "repeated" if self.is_repeated else "optional"
    if self.type is None:
      result = ["{} {}:".format(repeated_as_string, str(field_name))]
    else:
      result = [
          "{} {} {}".format(repeated_as_string, str(self.type), str(field_name))
      ]
    if limit is not None and limit == 0:
      if self.get_known_children():
        result.append("  ...")
      return result

    new_limit = None if limit is None else limit - 1

    for field_name, subexpression in self.get_known_children().items():
      recursive = subexpression._schema_string_helper(field_name, new_limit)  # pylint: disable=protected-access
      result.extend(["  {}".format(x) for x in recursive])
    return result

  # Begin methods compatible with v1 API. ######################################
  # TODO(martinz): Implement cogroup_by_index.
  def map_sparse_tensors(self, parent_path,
                         source_fields,
                         operator,
                         is_repeated, dtype,
                         new_field_name):
    """Maps a set of primitive fields of a message to a new field.

    Unlike map_field_values, this operation allows you to some degree reshape
    the field. For instance, you can take two optional fields and create a
    repeated field, or perform a reduce_sum on the last dimension of a repeated
    field and create an optional field. The key constraint is that the operator
    must return a sparse tensor of the correct dimension: i.e., a
    2D sparse tensor if is_repeated is true, or a 1D sparse tensor if
    is_repeated is false. Moreover, the first dimension of the sparse tensor
    must be equal to the first dimension of the input tensor.

    Args:
      parent_path: the parent of the input and output fields.
      source_fields: the nonempty list of names of the source fields.
      operator: an operator that takes len(source_fields) sparse tensors and
        returns a sparse tensor of the appropriate shape.
      is_repeated: whether the output is repeated.
      dtype: the dtype of the result.
      new_field_name: the name of the resulting field.

    Returns:
      A new query.
    """
    return map_prensor.map_sparse_tensor(
        self, path.create_path(parent_path),
        [path.Path([f]) for f in source_fields], operator, is_repeated, dtype,
        new_field_name)

  def map_ragged_tensors(self, parent_path,
                         source_fields,
                         operator,
                         is_repeated, dtype,
                         new_field_name):
    """Maps a set of primitive fields of a message to a new field.

    Unlike map_field_values, this operation allows you to some degree reshape
    the field. For instance, you can take two optional fields and create a
    repeated field, or perform a reduce_sum on the last dimension of a repeated
    field and create an optional field. The key constraint is that the operator
    must return a sparse tensor of the correct dimension: i.e., a
    2D sparse tensor if is_repeated is true, or a 1D sparse tensor if
    is_repeated is false. Moreover, the first dimension of the sparse tensor
    must be equal to the first dimension of the input tensor.

    Args:
      parent_path: the parent of the input and output fields.
      source_fields: the nonempty list of names of the source fields.
      operator: an operator that takes len(source_fields) sparse tensors and
        returns a sparse tensor of the appropriate shape.
      is_repeated: whether the output is repeated.
      dtype: the dtype of the result.
      new_field_name: the name of the resulting field.

    Returns:
      A new query.
    """
    return map_prensor.map_ragged_tensor(
        self, path.create_path(parent_path),
        [path.Path([f]) for f in source_fields], operator, is_repeated, dtype,
        new_field_name)

  def truncate(self, source_path, limit,
               new_field_name):
    """Creates a truncated copy of source_path at new_field_path."""
    return self.slice(source_path, new_field_name, end=limit)

  def slice(self,
            source_path,
            new_field_name,
            begin = None,
            end = None):
    """Creates a slice copy of source_path at new_field_path.

    Note that if begin or end is negative, it is considered relative to
    the size of the array. e.g., slice(...,begin=-1) will get the last
    element of every array.

    Args:
      source_path: the source of the slice.
      new_field_name: the new field that is generated.
      begin: the beginning of the slice (inclusive).
      end: the end of the slice (exclusive).

    Returns:
      An Expression object representing the result of the operation.
    """
    return slice_expression.slice_expression(self,
                                             path.create_path(source_path),
                                             new_field_name, begin, end)

  def promote(self, source_path, new_field_name):
    """Promotes source_path to be a field new_field_name in its grandparent."""
    return promote.promote(self, path.create_path(source_path), new_field_name)

  def broadcast(self, source_path, sibling_field,
                new_field_name):
    """Broadcasts the existing field at source_path to the sibling_field."""
    return broadcast_module.broadcast(self, path.create_path(source_path),
                                      sibling_field, new_field_name)

  def project(self, path_list):
    """Constrains the paths to those listed."""
    return project.project(self, [path.create_path(x) for x in path_list])

  def promote_and_broadcast(
      self, path_dictionary,
      dest_path_parent):
    return promote_and_broadcast.promote_and_broadcast(
        self, {k: path.create_path(v) for k, v in path_dictionary.items()},
        path.create_path(dest_path_parent))

  def map_field_values(self, source_path,
                       operator,
                       dtype,
                       new_field_name):
    """Map a primitive field to create a new primitive field.

    Note: the dtype argument is added since the v1 API.

    Args:
      source_path: the origin path.
      operator: an element-wise operator that takes a 1-dimensional vector.
      dtype: the type of the output.
      new_field_name: the name of a new sibling of source_path.

    Returns:
      the resulting root expression.
    """
    return map_values.map_values(self, path.create_path(source_path), operator,
                                 dtype, new_field_name)

  def reroot(self, new_root):
    """Returns a new list of protocol buffers available at new_root."""
    return reroot.reroot(self, path.create_path(new_root))

  def create_size_field(self, source_path,
                        new_field_name):
    """Creates a field that is the size of the source path."""
    return size.size(self, path.create_path(source_path), new_field_name)

  def create_has_field(self, source_path,
                       new_field_name):
    """Creates a field that is the presence of the source path."""
    return size.has(self, path.create_path(source_path), new_field_name)

  def create_proto_index(self, field_name):
    """Creates a proto index field as a direct child of the current root.

    The proto index maps each root element to the original batch index.
    For example: [0, 2] means the first element came from the first proto
    in the original input tensor and the second element came from the third
    proto. The created field is always "dense" -- it has the same valency as
    the current root.

    Args:
      field_name: the name of the field to be created.

    Returns:
      An Expression object representing the result of the operation.
    """

    return reroot.create_proto_index_field(self, field_name)

  def cogroup_by_index(self, source_path, left_name,
                       right_name,
                       new_field_name):
    """Creates a cogroup of left_name and right_name at new_field_name."""
    raise NotImplementedError("cogroup_by_index is not implemented")

  # End methods compatible with v1 API. ########################################

  def apply(self,
            transform):
    return transform(self)

  def apply_schema(self, schema):
    return apply_schema.apply_schema(self, schema)

  def _populate_schema_feature_children(self, feature_list):
    """Populate a feature list from the children of this node.

    The argument is a protobuf repeated field that is populated. The names
    of the features come from the leaf names.

    Args:
      feature_list: RepeatedCompositeFieldContainer of schema_pb2.Feature.
    """
    for name, child in self.get_known_children().items():
      new_feature = feature_list.add()
      if child.schema_feature is None:
        if not child.is_repeated:
          new_feature.value_count.max = 1
      else:
        new_feature.CopyFrom(child.schema_feature)
      if child.get_known_children():
        child._populate_schema_feature_children(  # pylint:disable=protected-access
            new_feature.struct_domain.feature)
      new_feature.name = name

  def get_schema(self):
    """Returns a schema for the entire tree."""
    result = schema_pb2.Schema()
    self._populate_schema_feature_children(result.feature)
    return result

  def schema_string(self, limit = None):  # pylint: disable=g-ambiguous-str-annotation
    """Returns a schema for the expression.

    E.g.

    repeated root:
      optional int32 foo
      optional bar:
        optional string baz
      optional int64 bak

    Note that unknown fields and subexpressions are not displayed.

    Args:
      limit: if present, limit the recursion.

    Returns:
      A string, describing (a part of) the schema.
    """
    return "\n".join(self._schema_string_helper("root", limit))

  def __str__(self):  # pylint: disable=g-ambiguous-str-annotation
    """If not overridden, returns the schema string."""
    return self.schema_string(limit=20)


# TODO(martinz): this will be tested when broadcast is created.
class Leaf(Expression):
  """An abstract supertype for expression subtypes without any children."""

  def __init__(self,
               is_repeated,
               my_type,
               schema_feature = None):  # pylint: disable=useless-super-delegation
    """Initialize a Leaf.

    Note that a leaf must have a specified type.

    Args:
      is_repeated: if the expression is repeated.
      my_type: the DType of the field.
      schema_feature: schema information about the field.
    """
    super(Leaf, self).__init__(
        is_repeated, my_type, schema_feature=schema_feature)

  def _get_child_impl(self, field_name):
    return None

  def known_field_names(self):
    return frozenset()
