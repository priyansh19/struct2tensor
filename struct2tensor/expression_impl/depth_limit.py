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

r"""Caps the depth of an expression.

Suppose you have an expression expr modeled as:

  *
   \
    A
   / \
  D   B
       \
        C

if expr_2 = depth_limit.limit_depth(expr, 2)
You get:

  *
   \
    A
   / \
  D   B

"""

from __future__ import absolute_import
from __future__ import division

from __future__ import print_function

from struct2tensor import calculate_options
from struct2tensor import expression
from struct2tensor import path
from struct2tensor import prensor
from typing import FrozenSet, Optional, Sequence


def limit_depth(expr,
                depth_limit):
  """Limit the depth to nodes k steps from expr."""
  return _DepthLimitExpression(expr, depth_limit)


class _DepthLimitExpression(expression.Expression):
  """Project all subfields of an expression."""

  def __init__(self, origin, depth_limit):
    super(_DepthLimitExpression, self).__init__(origin.is_repeated, origin.type)
    self._origin = origin
    self._depth_limit = depth_limit

  def get_source_expressions(self):
    return [self._origin]

  def calculate(self, sources,
                destinations,
                options):
    if len(sources) != 1:
      raise ValueError("Expected one source.")
    return sources[0]

  def calculation_is_identity(self):
    return True

  def calculation_equal(self, expr):
    return expr.calculation_is_identity()

  def _get_child_impl(self,
                      field_name):
    if self._depth_limit == 0:
      return None
    origin_child = self._origin.get_child(field_name)
    if origin_child is None:
      return None
    return _DepthLimitExpression(origin_child, self._depth_limit - 1)

  def known_field_names(self):
    if self._depth_limit == 0:
      return frozenset()
    return self._origin.known_field_names()
