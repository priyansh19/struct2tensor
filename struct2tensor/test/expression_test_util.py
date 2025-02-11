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
"""A reference implementation for calculating the node tensor of an expression.

This method is very slow, and should only be used for testing purposes.
"""

from __future__ import absolute_import
from __future__ import division

from __future__ import print_function

from struct2tensor import calculate
from struct2tensor import calculate_options
from struct2tensor import expression
from struct2tensor import path
from struct2tensor import prensor
from struct2tensor import prensor_util
import tensorflow as tf
from typing import FrozenSet, Optional, Mapping, Sequence, Text

from tensorflow_metadata.proto.v0 import schema_pb2


def calculate_value_slowly(
    expr,
    destinations = None,
    options = None):
  """A calculation of the node tensor of an expression, without optimization.

  This will not do any common subexpression elimination or caching of
  node tensors, and will likely be very slow for larger operations.

  Args:
    expr: The expression to calculate.
    destinations: Where the calculation will be used (None implies directly)
    options: Calculation options for individual calculations

  Returns:
    The node tensor of the expression.
  """
  new_options = calculate_options.get_default_options(
  ) if options is None else options

  source_node_tensors = [
      calculate_value_slowly(x, [expr], new_options)
      for x in expr.get_source_expressions()
  ]
  real_dest = [] if destinations is None else destinations
  return expr.calculate(source_node_tensors, real_dest, new_options)


def calculate_list_map(expr, sess):
  """Calculate a map from paths to nested lists, representing the leafs."""
  [my_prensor] = calculate.calculate_prensors([expr])
  ragged_tensor_map = prensor_util.get_ragged_tensors(
      my_prensor, calculate_options.get_default_options())
  string_tensor_map = {str(k): v for k, v in ragged_tensor_map.items()}
  string_np_map = sess.run(string_tensor_map)
  return {k: v.to_list() for k, v in string_np_map.items()}


class MockExpression(expression.Expression):
  """The mock expression is designed to test calculations."""

  def __init__(
      self,
      is_repeated,
      my_type,
      name = None,
      source_expressions = None,
      calculate_output = None,
      calculate_is_identity = False,
      children = None,
      known_field_names = None,
      schema_feature = None):
    """Initialize an expression.

    Args:
      is_repeated: whether the output is_repeated.
      my_type: what my type is.
      name: the name of this expression.
      source_expressions: the source expressions.
      calculate_output: the output returned.
      calculate_is_identity: if this returns the identity.
      children: the children of this expression
      known_field_names: the known children of this expression.
      schema_feature: schema information about the feature.
    """
    super(MockExpression, self).__init__(
        is_repeated, my_type, schema_feature=schema_feature)
    self._name = "Unknown" if name is None else name
    self._source_expressions = []
    if source_expressions is not None:
      self._source_expressions = source_expressions
    self._expected_source_tensors = [
        x.calculate_output for x in self._source_expressions
    ]
    self._calculate_output = calculate_output
    self._calculate_is_identity = calculate_is_identity
    self._children = {} if children is None else children
    if known_field_names is None:
      self._known_field_names = frozenset(self._children.keys())
    else:
      self._known_field_names = known_field_names

  @property
  def calculate_output(self):
    """The output returned by this expression."""
    if self._calculate_output is None:
      raise ValueError("Did not specify calculate_output for {}".format(self._name))
    return self._calculate_output

  def get_source_expressions(self):
    return self._source_expressions

  def calculate(self, source_tensors,
                destinations,
                options):
    if len(source_tensors) != len(self._expected_source_tensors):
      raise ValueError("Unexpected number of inputs for {}.".format(self._name))
    for i in range(len(source_tensors)):
      if self._expected_source_tensors[i] is not source_tensors[i]:
        raise ValueError("Error calculating " + self._name)
    return self._calculate_output

  def calculation_is_identity(self):
    return self._calculate_is_identity

  def calculation_equal(self, expr):
    return self.calculation_is_identity() and expr.calculation_is_identity()

  def _get_child_impl(self,
                      field_name):
    return self._children.get(field_name)

  def known_field_names(self):
    return self._known_field_names

  def __str__(self):  # pylint: disable=g-ambiguous-str-annotation
    return str(self._name)


def get_mock_leaf(is_repeated,
                  my_type,
                  name = None,
                  source_expressions = None,
                  calculate_is_identity = False):
  """Gets a leaf expression."""
  if calculate_is_identity:
    calculate_output = source_expressions[0].calculate_output
  else:
    calculate_output = prensor.LeafNodeTensor(
        tf.constant([], dtype=tf.int64), tf.constant([], dtype=my_type),
        is_repeated)
  return MockExpression(
      is_repeated,
      my_type,
      name=name,
      source_expressions=source_expressions,
      calculate_output=calculate_output,
      calculate_is_identity=calculate_is_identity)


def get_mock_broken_leaf(
    declared_is_repeated,
    declared_type,
    actual_is_repeated,
    actual_type,
    name = None,
    source_expressions = None,
    calculate_is_identity = False):
  """Gets a leaf expression flexible enough not to typecheck.

  If declared_is_repeated != actual_is_repeated,
  or declared_type != actual_type, then this will not typecheck
  when _ExpressionNode.calculate() is called.

  Args:
    declared_is_repeated: the is_repeated of the expression.
    declared_type: the type of the expression.
    actual_is_repeated: the is_repeated of the NodeTensor.
    actual_type: the type of the NodeTensor.
    name: a name of the expression.
    source_expressions: the result of get_source expressions()
    calculate_is_identity: true iff this should say it is the identity.

  Returns:
    An expression.

  """
  if calculate_is_identity:
    calculate_output = source_expressions[0].calculate_output
  else:
    calculate_output = prensor.LeafNodeTensor(
        tf.constant([], dtype=tf.int64), tf.constant([], dtype=actual_type),
        actual_is_repeated)
  return MockExpression(
      declared_is_repeated,
      declared_type,
      name=name,
      source_expressions=source_expressions,
      calculate_output=calculate_output,
      calculate_is_identity=calculate_is_identity)
