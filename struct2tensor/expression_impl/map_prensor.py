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
"""Arbitrary operations from sparse and ragged tensors to a leaf field.

There are two public methods of note right now: map_sparse_tensor
and map_ragged_tensor.

Assume expr is:
session: {
  event: {
    val_a: 10
    val_b: 1
  }
  event: {
    val_a: 20
    val_b: 2
  }
  event: {
  }
  event: {
    val_a: 40
  }
  event: {
    val_b: 5
  }
}

Either of the following alternatives will add val_a and val_b
to create val_sum.

map_sparse_tensor converts val_a and val_b to sparse tensors,
and then add them to produce val_sum.
new_root = map_prensor.map_sparse_tensor(
    expr,
    path.Path(["event"]),
    [path.Path(["val_a"]), path.Path(["val_b"])],
    lambda x,y: x + y,
    False,
    tf.int32,
    "val_sum")

map_ragged_tensor converts val_a and val_b to ragged tensors,
and then add them to produce val_sum.
new_root = map_prensor.map_ragged_tensor(
    expr,
    path.Path(["event"]),
    [path.Path(["val_a"]), path.Path(["val_b"])],
    lambda x,y: x + y,
    False,
    tf.int32,
    "val_sum")

The result of either is:

session: {
  event: {
    val_a: 10
    val_b: 1
    val_sum: 11
  }
  event: {
    val_a: 20
    val_b: 2
    val_sum: 22
  }
  event: {
  }
  event: {
    val_a: 40
    val_sum: 40
  }
  event: {
    val_b: 5
    val_sum: 5
  }
}


"""

from __future__ import absolute_import
from __future__ import division

from __future__ import print_function

from struct2tensor import calculate_options
from struct2tensor import expression
from struct2tensor import expression_add
from struct2tensor import path
from struct2tensor import prensor
from struct2tensor import prensor_util
from struct2tensor.expression_impl import project
import tensorflow as tf
from typing import Callable, FrozenSet, Optional, Sequence, Tuple


def map_sparse_tensor(root, root_path,
                      paths,
                      operation,
                      is_repeated, dtype,
                      new_field_name):
  """Maps a sparse tensor.

  Args:
    root: the root of the expression.
    root_path: the path relative to which the sparse tensors are calculated.
    paths: the input paths relative to the root_path
    operation: a method that takes the list of sparse tensors as input and
      returns a sparse tensor.
    is_repeated: true if the result of operation is repeated.
    dtype: dtype of the result of the operation.
    new_field_name: root_path.get_child(new_field_name) is the path of the
      result.

  Returns:
    A new root expression containing the old root expression plus the new path,
    root_path.get_child(new_field_name), with the result of the operation.
  """

  return _map_sparse_tensor_impl(root, root_path, paths, operation, is_repeated,
                                 dtype, new_field_name)[0]


def map_ragged_tensor(root, root_path,
                      paths,
                      operation,
                      is_repeated, dtype,
                      new_field_name):
  """Map a ragged tensor.

  Args:
    root: the root of the expression.
    root_path: the path relative to which the ragged tensors are calculated.
    paths: the input paths relative to the root_path
    operation: a method that takes the list of ragged tensors as input and
      returns a ragged tensor.
    is_repeated: true if the result of operation is repeated.
    dtype: dtype of the result of the operation.
    new_field_name: root_path.get_child(new_field_name) is the path of the
      result.

  Returns:
    A new root expression containing the old root expression plus the new path,
    root_path.get_child(new_field_name), with the result of the operation.
  """
  return _map_ragged_tensor_impl(root, root_path, paths, operation, is_repeated,
                                 dtype, new_field_name)[0]


class _MapPrensorExpression(expression.Expression):
  """Maps the values of the given expression.

  It maps the value of a sub-tree (i.e. a Prensor) to a single prensor
  LeafNodeTensor. Therefore its sources are all the (known) descendants of
  `origin`: it usually should follow a project(...) to make known descendants
  clear.

  _MapPrensorExpression is intended to be a child of the origin. See
  map_prensor_impl for example usage.

  """

  def __init__(self, origin,
               operation,
               is_repeated, dtype):
    super(_MapPrensorExpression, self).__init__(is_repeated, dtype)
    self._origin = origin
    self._operation = operation

  def _get_source_paths(self):
    """Returns the source paths in a deterministic order."""
    result = [k for k in self._origin.get_known_descendants().keys()]
    result.sort()
    return result

  def get_source_expressions(self):
    subtree = self._origin.get_known_descendants()
    source_paths = self._get_source_paths()
    return [subtree[k] for k in source_paths]

  def calculate(self, sources,
                destinations,
                options):
    print("map_prensor:calculate:options:{}".format(options))

    source_tree = prensor.create_prensor_from_descendant_nodes(
        {k: v for k, v in zip(self._get_source_paths(), sources)})
    return self._operation(source_tree, options)

  def calculation_is_identity(self):
    return False

  def calculation_equal(self, expr):
    return self is expr

  def _get_child_impl(self,
                      field_name):
    return None

  def known_field_names(self):
    return frozenset()


def _as_leaf_node_no_checks(sparse_tensor,
                            is_repeated):
  """Take a SparseTensor and create a LeafNodeTensor, no checks."""
  if is_repeated:
    parent_index = tf.transpose(sparse_tensor.indices)[0]
  else:
    parent_index = tf.reshape(sparse_tensor.indices, [-1])
  return prensor.LeafNodeTensor(parent_index, sparse_tensor.values, is_repeated)


def _as_leaf_node_with_checks(sparse_tensor, is_repeated,
                              required_batch_size
                             ):
  """Take a SparseTensor and create a LeafNodeTensor, with checks."""
  assertions = [
      tf.assert_equal(sparse_tensor.dense_shape[0], required_batch_size)
  ]
  if is_repeated:
    assertions.append(tf.assert_equal(tf.shape(sparse_tensor.indices)[1], 2))
  else:
    assertions.append(tf.assert_equal(tf.shape(sparse_tensor.indices)[1], 1))

  with tf.control_dependencies(assertions):
    # TODO(b/72947444): Check that the resulting tensor is canonical, that the
    # indices are in lexicographical order, and that the indices fit in the
    # shape. Moreover, maybe we should check if it is repeated that it is a
    # "ragged array".
    return _as_leaf_node_no_checks(sparse_tensor, is_repeated)


def _as_leaf_node(sparse_tensor, is_repeated,
                  required_batch_size,
                  options):
  if options.sparse_checks:
    print("Using sparse_checks")
    return _as_leaf_node_with_checks(sparse_tensor, is_repeated,
                                     required_batch_size)
  else:
    print("NOT Using sparse_checks")
    return _as_leaf_node_no_checks(sparse_tensor, is_repeated)


def _map_prensor_impl(
    root, root_path,
    paths_needed,
    operation, is_repeated, dtype,
    new_field_name):
  """Map prensor implementation."""
  child_expr = root.get_descendant_or_error(root_path)
  sibling_child_expr = project.project(child_expr, paths_needed)
  new_field_expr = _MapPrensorExpression(sibling_child_expr, operation,
                                         is_repeated, dtype)
  new_path = root_path.get_child(new_field_name)
  return expression_add.add_paths(root, {new_path: new_field_expr}), new_path


def _map_sparse_tensor_impl(root, root_path,
                            paths,
                            operation,
                            is_repeated, dtype,
                            new_field_name
                           ):
  """Helper method for map_sparse_tensor."""

  def new_op(pren,
             options):
    """Op for mapping prensor using the operation."""
    sparse_tensor_map = prensor_util.get_sparse_tensors(pren, options)
    sparse_tensors = [sparse_tensor_map[p] for p in paths]
    result_as_tensor = operation(*sparse_tensors)
    result = _as_leaf_node(result_as_tensor, is_repeated,
                           sparse_tensors[0].dense_shape[0], options)
    if result.values.dtype != dtype:
      raise ValueError("Type unmatched: actual ({})!= expected ({})".format(
          str(result.values.dtype), str(dtype)))
    return result

  return _map_prensor_impl(root, root_path, paths, new_op, is_repeated, dtype,
                           new_field_name)


def _ragged_as_leaf_node(ragged_tensor, is_repeated,
                         reference_ragged_tensor,
                         options
                        ):
  """Creates a ragged tensor as a leaf node."""
  assertions = []
  if (ragged_tensor.shape[0].value is not None and
      reference_ragged_tensor.shape[0].value is not None):
    if ragged_tensor.shape[0].value != reference_ragged_tensor.shape[0].value:
      raise ValueError("Returned ragged tensor is not the right size.")
  elif options.ragged_checks:
    assertions.append(
        tf.assert_equal(ragged_tensor.nrows(), reference_ragged_tensor.nrows()))

  if not is_repeated:
    rowids = ragged_tensor.value_rowids()
    if options.ragged_checks:
      assertions.append(tf.compat.v1.assert_positive(rowids[1:] - rowids[:-1]))
  if assertions:
    with tf.control_dependencies(assertions):
      parent_index = ragged_tensor.value_rowids()
      return prensor.LeafNodeTensor(parent_index, ragged_tensor.values,
                                    is_repeated)
  else:
    parent_index = ragged_tensor.value_rowids()
    return prensor.LeafNodeTensor(parent_index, ragged_tensor.values,
                                  is_repeated)


def _map_ragged_tensor_impl(root, root_path,
                            paths,
                            operation,
                            is_repeated, dtype,
                            new_field_name
                           ):
  """Maps a ragged tensor.

  Args:
    root: the root of the expression.
    root_path: the path relative to which the ragged tensors are calculated.
    paths: the input paths relative to the root_path
    operation: a method that takes the list of ragged tensors as input and
      returns a ragged tensor.
    is_repeated: true if the result of operation is repeated.
    dtype: dtype of the result of the operation.
    new_field_name: root_path.get_child(new_field_name) is the path of the
      result.

  Returns:
    An expression/path pair (expr,p) with a new root expression containing
    the old root expression plus the new path,
    root_path.get_child(new_field_name), with the result of the operation.
  """

  def new_op(tree,
             options):
    """Apply operation to tree."""
    ragged_tensor_map = prensor_util.get_ragged_tensors(tree, options)
    ragged_tensors = [ragged_tensor_map[p] for p in paths]
    result_as_tensor = operation(*ragged_tensors)
    result = _ragged_as_leaf_node(result_as_tensor, is_repeated,
                                  ragged_tensors[0], options)
    if result.values.dtype != dtype:
      raise ValueError("Type unmatched: actual ({})!= expected ({})".format(
          str(result.values.dtype), str(dtype)))
    return result

  return _map_prensor_impl(root, root_path, paths, new_op, is_repeated, dtype,
                           new_field_name)
