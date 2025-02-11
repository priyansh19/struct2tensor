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
"""A Path representing a path from the root in a prensor expression.

For simple cases, the path can be specified as a string. However,
if there is a need to create a path directly or perform various operations
such as getting a child or a parent, a client may find this class useful.

"""

# pylint: disable=g-ambiguous-str-annotation
from __future__ import absolute_import
from __future__ import division

from __future__ import print_function

import re
from typing import Sequence, Tuple, Union

from tensorflow_metadata.proto.v0 import path_pb2 as tf_metadata_path_pb2

# This is for extensions and Any.
_EXTENSION_REGEX = r"""(?:\((?:[A-Za-z0-9_/\-]+\.)*[A-Za-z0-9_/\-]+\))"""
_SIMPLE_STEP_REGEX = r"""(?:[A-Za-z0-9_\-]+)"""

# This is for map indexing syntax. Note that we don't allow the map index to
# contain "]" currently as it complicates the parsing. However the rest of the
# Prensor library works with such a step fine.
_MAP_INDEXING_STEP_REGEX = r"""(?:[A-Za-z0-9_\-]+\[[^]]*\])"""

AnonymousId = int
Step = Union[AnonymousId, str]  # pylint: disable=invalid-name

_NEXT_ANONYMOUS_FIELD = 0


def get_anonymous_field():
  """Gets a globally unique anonymous field."""
  # TODO(martinz): Add thread safety here.
  global _NEXT_ANONYMOUS_FIELD
  result = _NEXT_ANONYMOUS_FIELD
  _NEXT_ANONYMOUS_FIELD += 1
  return result


def _compare_step(a, b):
  """Return positive, zero, or negative if a>b, a==b, or a<b, respectively.

  AnonymousIds are greater than string values.

  Args:
    a: A step.
    b: A step.

  Returns:
    positive, zero, or negative if a>b, a==b, or a<b, respectively.
  """
  aint = isinstance(a, AnonymousId)
  bint = isinstance(b, AnonymousId)

  if aint == bint:
    if a > b:
      return 1
    elif a < b:
      return -1
    return 0

  if aint:
    return 1
  return -1


class Path(object):
  """A representation of a path in the expression.

  Do not implement __nonzero__, __eq__, __ne__, et cetera as these are
  implicitly defined by __cmp__ and __len__.

  """

  def __init__(self, field_list):
    """Create a path object.

    Args:
      field_list: a list or tuple of fields leading from one node to another.

    Raises:
      ValueError: if any field is not a valid step (see is_valid_step).
    """
    for field in field_list:
      if isinstance(field, str) and not is_valid_step(field):
        raise ValueError('Field "' + field + '" is invalid.')
    self.field_list = tuple(field_list)

  def __cmp__(self, other):
    """Lexicographical ordering of paths.

    If one path is a strict prefix of the other, the prefix is less.
    Otherwise, the prefix of the longer path is compared to the shorter path.

    Args:
      other: the path to compare to.

    Returns:
     -1, 0, or 1 if this is <,==, or > other
    """
    for i in range(min(len(self.field_list), len(other.field_list))):
      step_diff = _compare_step(self.field_list[i], other.field_list[i])
      if step_diff > 0:
        return step_diff
      if step_diff < 0:
        return step_diff
    len_diff = len(self.field_list) - len(other.field_list)
    if len_diff > 0:
      return 1
    if len_diff < 0:
      return -1
    return 0

  def __eq__(self, other):
    return self.__cmp__(other) == 0

  def __ne__(self, other):
    return self.__cmp__(other) != 0

  def __le__(self, other):
    return self.__cmp__(other) <= 0

  def __lt__(self, other):
    return self.__cmp__(other) < 0

  def __ge__(self, other):
    return self.__cmp__(other) >= 0

  def __gt__(self, other):
    return self.__cmp__(other) > 0

  def __hash__(self):
    return hash(self.field_list)

  def get_parent(self):
    """Get the parent path.

    Returns:
      The parent path.

    Raises:
      ValueError: If this is the root path.
    """
    if not self:
      raise ValueError("Tried to find parent of root")
    return Path(self.field_list[:-1])

  def get_child(self, field_name):
    """Get the child path."""
    if isinstance(field_name, str) and not is_valid_step(field_name):
      raise ValueError("field_name is not valid: " + field_name)
    return Path(self.field_list + (field_name,))

  def concat(self, other_path):
    return Path(self.field_list + other_path.field_list)

  def prefix(self, ending_index):
    return Path(self.field_list[:ending_index])

  def suffix(self, starting_index):
    return Path(self.field_list[starting_index:])

  def __len__(self):
    return len(self.field_list)

  def _get_least_common_ancestor_len(self, other):
    """Get the length of the LCA path (the longest shared prefix)."""
    min_length = min(len(self.field_list), len(other.field_list))
    for i in range(min_length):
      if self.field_list[i] != other.field_list[i]:
        return i
    return min_length

  def get_least_common_ancestor(self, other):
    """Get the least common ancestor, the longest shared prefix."""
    lca_len = self._get_least_common_ancestor_len(other)
    return Path(self.field_list[:lca_len])

  def is_ancestor(self, other):
    """True if self is ancestor of other (i.e. a prefix)."""
    return len(self.field_list) <= len(other.field_list) and self == Path(
        other.field_list[:len(self.field_list)])

  def as_proto(self):
    """Serialize a path as a proto.

    This fails if there are any anonymous fields.

    Returns:
      a Path proto.
    """
    result = tf_metadata_path_pb2.Path()
    for x in self.field_list:
      if isinstance(x, str):
        result.step.append(x)
      elif isinstance(x, AnonymousId):
        raise ValueError("Cannot serialize a path with anonymous fields")
      else:
        raise ValueError("Unexpected path element type: %s" % type(x))
    return result

  def __str__(self):
    """Get a string representation of this path.

    Note that if some fields have periods in them, then:
      create_path(str(path)) != path

    Returns:
      A string representation of the path, using periods.
    """
    return ".".join([str(x) for x in self.field_list])


def is_valid_step(step_str):
  """Return true if step_str is a valid step (see create_path)."""
  return re.match(
      "(?:" + _EXTENSION_REGEX + "|" + _SIMPLE_STEP_REGEX + "|" +
      _MAP_INDEXING_STEP_REGEX + ")$", step_str, re.VERBOSE) is not None


def is_extension(step_str):
  """Return true if step_str is an extension or Any.

  Args:
    step_str: the string to evaluate

  Returns:
    True if step_str is an extension
  Raises:
    ValueError: if step_str is not a valid step.
  """
  if not is_valid_step(step_str):
    raise ValueError('Not a valid step in a path: "' + step_str + '"')
  return step_str[0] == "("


def get_raw_extension_name(step_str):
  """Gets the step without the parentheses."""
  if not is_valid_step(step_str):
    raise ValueError('Not a valid step in a path: "' + step_str + '"')
  if not is_extension(step_str):
    raise ValueError('Not an extension: "' + step_str + '"')
  return step_str[1:-1]


# The purpose of this type is to make it easy to write down paths as literals.
# If we made it Text instead of str, then it wouldn't be easy anymore.
# For example, suppose you have:
# CoercableToPath = Union[Path, Text]
# Then, to typecheck in Python 2, you would have to write:
# create_path(u"foo.bar")
# If you don't have Python 2, then there is no difference between Text and str.
CoercableToPath = Union[Path, str]


def is_map_indexing_step(step):
  return re.match(_MAP_INDEXING_STEP_REGEX, step, re.VERBOSE) is not None


def parse_map_indexing_step(step):
  first_bracket = step.find("[")
  return step[:first_bracket], step[first_bracket + 1:-1]


def create_path(path_source):
  """Create a path from an object.

  The BNF for a path is:
  letter := [A-Za-z]
  digit := [0-9]
  <simple_step_char> := "_"|"-"| | letter | digit
  <simple_step> := <simple_step_char>+
  <extension> := "(" (<simple_step> ".")* <simple_step> ")"
  <step> := <simple_step> | <extension>
  <path> := ((<step> ".") * <step>)?

  TODO(martinz): consider removing dash. This would break YouTube WatchNext.

  Args:
    path_source: a string or a Path object.

  Returns:
    A Path.
  Raises:
    ValueError: if this is not a valid path.
  """
  if isinstance(path_source, Path):
    return path_source
  if path_source and path_source[-1] == ".":
    # If we removed this then the period at the end would be ignored, and
    # "foo.bar." would become ['foo', 'bar']
    raise ValueError("Path cannot end with .")
  result = []
  path_remaining = path_source
  # Capture a simple or extension step, then capture the next dot or end.
  path_step_separator_re = re.compile(
      "(" + _EXTENSION_REGEX + "|" + _SIMPLE_STEP_REGEX + "|" +
      _MAP_INDEXING_STEP_REGEX + r""")(\.|$)""", re.VERBOSE)
  while path_remaining:
    next_match = path_step_separator_re.match(path_remaining)
    if next_match:
      result.append(next_match.group(1))
      path_remaining = path_remaining[next_match.end():]
    else:
      raise ValueError("Malformed path:  " + path_source)
  return Path(result)


def from_proto(path_proto):
  # Coerce each step to a native string. The steps in the proto are always
  # Unicode strings, but the Path class may contain either unicode or bytes
  # depending on whether this module is loaded with Python2 or Python3.
  return Path([str(step) for step in path_proto.step])
