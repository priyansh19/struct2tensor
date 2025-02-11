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
"""Tests for struct2tensor.promote."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf

import unittest
from struct2tensor import create_expression
from struct2tensor.test import expression_test_util
from struct2tensor import path
from struct2tensor.test import prensor_test_util
from struct2tensor.expression_impl import index


class IndexTest(unittest.TestCase):

  def test_get_positional_index(self):
    expr = create_expression.create_expression_from_prensor(
        prensor_test_util.create_nested_prensor())
    new_root, new_path = index.get_positional_index(
        expr, path.Path(["user", "friends"]), path.get_anonymous_field())
    new_field = new_root.get_descendant_or_error(new_path)
    self.assertTrue(new_field.is_repeated)
    self.assertEqual(new_field.type, tf.int64)
    self.assertTrue(new_field.is_leaf)
    self.assertTrue(new_field.calculation_equal(new_field))
    self.assertFalse(new_field.calculation_equal(expr))
    leaf_node = expression_test_util.calculate_value_slowly(new_field)
    self.assertEqual(leaf_node.values.dtype, tf.int64)
    self.assertEqual(new_field.known_field_names(), frozenset())

  def test_get_index_from_end(self):
    expr = create_expression.create_expression_from_prensor(
        prensor_test_util.create_nested_prensor())
    new_root, new_path = index.get_index_from_end(
        expr, path.Path(["user", "friends"]), path.get_anonymous_field())
    new_field = new_root.get_descendant_or_error(new_path)
    self.assertTrue(new_field.is_repeated)
    self.assertEqual(new_field.type, tf.int64)
    self.assertTrue(new_field.is_leaf)
    self.assertTrue(new_field.calculation_equal(new_field))
    self.assertFalse(new_field.calculation_equal(expr))
    leaf_node = expression_test_util.calculate_value_slowly(new_field)
    self.assertEqual(leaf_node.values.dtype, tf.int64)
    self.assertEqual(new_field.known_field_names(), frozenset())


class GetIndexValuesTest(tf.test.TestCase):

  def test_get_positional_index_calculate(self):
    with self.session(use_gpu=False) as sess:
      expr = create_expression.create_expression_from_prensor(
          prensor_test_util.create_nested_prensor())
      new_root, new_path = index.get_positional_index(
          expr, path.Path(["user", "friends"]), path.get_anonymous_field())
      new_field = new_root.get_descendant_or_error(new_path)
      leaf_node = expression_test_util.calculate_value_slowly(new_field)
      [parent_index,
       values] = sess.run([leaf_node.parent_index, leaf_node.values])

      self.assertAllEqual(parent_index, [0, 1, 1, 2, 3])
      self.assertAllEqual(values, [0, 0, 1, 0, 0])

  def test_get_index_from_end_calculate(self):
    with self.session(use_gpu=False) as sess:
      expr = create_expression.create_expression_from_prensor(
          prensor_test_util.create_nested_prensor())
      new_root, new_path = index.get_index_from_end(
          expr, path.Path(["user", "friends"]), path.get_anonymous_field())
      print("test_get_index_from_end_calculate: new_path: {}".format(new_path))
      new_field = new_root.get_descendant_or_error(new_path)
      print("test_get_index_from_end_calculate: new_field: {}".format(
          str(new_field)))

      leaf_node = expression_test_util.calculate_value_slowly(new_field)
      print("test_get_index_from_end_calculate: leaf_node: {}".format(
          str(leaf_node)))

      [parent_index,
       values] = sess.run([leaf_node.parent_index, leaf_node.values])

      self.assertAllEqual(parent_index, [0, 1, 1, 2, 3])
      self.assertAllEqual(values, [-1, -2, -1, -1, -1])


if __name__ == "__main__":
  unittest.main()
