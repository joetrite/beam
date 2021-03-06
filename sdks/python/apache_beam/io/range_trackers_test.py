#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""Unit tests for the range_trackers module."""

import array
import copy
import logging
import math
import unittest


from apache_beam.io import range_trackers


class OffsetRangeTrackerTest(unittest.TestCase):

  def test_try_return_record_simple_sparse(self):
    tracker = range_trackers.OffsetRangeTracker(100, 200)
    self.assertTrue(tracker.try_claim(110))
    self.assertTrue(tracker.try_claim(140))
    self.assertTrue(tracker.try_claim(183))
    self.assertFalse(tracker.try_claim(210))

  def test_try_return_record_simple_dense(self):
    tracker = range_trackers.OffsetRangeTracker(3, 6)
    self.assertTrue(tracker.try_claim(3))
    self.assertTrue(tracker.try_claim(4))
    self.assertTrue(tracker.try_claim(5))
    self.assertFalse(tracker.try_claim(6))

  def test_try_return_record_continuous_until_split_point(self):
    tracker = range_trackers.OffsetRangeTracker(9, 18)
    # Return records with gaps of 2; every 3rd record is a split point.
    self.assertTrue(tracker.try_claim(10))
    tracker.set_current_position(12)
    tracker.set_current_position(14)
    self.assertTrue(tracker.try_claim(16))
    # Out of range, but not a split point...
    tracker.set_current_position(18)
    tracker.set_current_position(20)
    # Out of range AND a split point.
    self.assertFalse(tracker.try_claim(22))

  def test_split_at_offset_fails_if_unstarted(self):
    tracker = range_trackers.OffsetRangeTracker(100, 200)
    self.assertFalse(tracker.try_split(150))

  def test_split_at_offset(self):
    tracker = range_trackers.OffsetRangeTracker(100, 200)
    self.assertTrue(tracker.try_claim(110))
    # Example positions we shouldn't split at, when last record starts at 110:
    self.assertFalse(tracker.try_split(109))
    self.assertFalse(tracker.try_split(110))
    self.assertFalse(tracker.try_split(200))
    self.assertFalse(tracker.try_split(210))
    # Example positions we *should* split at:
    self.assertTrue(copy.copy(tracker).try_split(111))
    self.assertTrue(copy.copy(tracker).try_split(129))
    self.assertTrue(copy.copy(tracker).try_split(130))
    self.assertTrue(copy.copy(tracker).try_split(131))
    self.assertTrue(copy.copy(tracker).try_split(150))
    self.assertTrue(copy.copy(tracker).try_split(199))

    # If we split at 170 and then at 150:
    self.assertTrue(tracker.try_split(170))
    self.assertTrue(tracker.try_split(150))
    # Should be able  to return a record starting before the new stop offset.
    # Returning records starting at the same offset is ok.
    self.assertTrue(copy.copy(tracker).try_claim(135))
    self.assertTrue(copy.copy(tracker).try_claim(135))
    # Should be able to return a record starting right before the new stop
    # offset.
    self.assertTrue(copy.copy(tracker).try_claim(149))
    # Should not be able to return a record starting at or after the new stop
    # offset.
    self.assertFalse(tracker.try_claim(150))
    self.assertFalse(tracker.try_claim(151))
    # Should accept non-splitpoint records starting after stop offset.
    tracker.set_current_position(135)
    tracker.set_current_position(152)
    tracker.set_current_position(160)
    tracker.set_current_position(171)

  def test_get_position_for_fraction_dense(self):
    # Represents positions 3, 4, 5.
    tracker = range_trackers.OffsetRangeTracker(3, 6)

    # Position must be an integer type.
    self.assertTrue(isinstance(tracker.position_at_fraction(0.0), (int, long)))
    # [3, 3) represents 0.0 of [3, 6)
    self.assertEqual(3, tracker.position_at_fraction(0.0))
    # [3, 4) represents up to 1/3 of [3, 6)
    self.assertEqual(4, tracker.position_at_fraction(1.0 / 6))
    self.assertEqual(4, tracker.position_at_fraction(0.333))
    # [3, 5) represents up to 2/3 of [3, 6)
    self.assertEqual(5, tracker.position_at_fraction(0.334))
    self.assertEqual(5, tracker.position_at_fraction(0.666))
    # Any fraction consumed over 2/3 means the whole [3, 6) has been consumed.
    self.assertEqual(6, tracker.position_at_fraction(0.667))

  def test_get_fraction_consumed_dense(self):
    tracker = range_trackers.OffsetRangeTracker(3, 6)
    self.assertEqual(0, tracker.fraction_consumed())
    self.assertTrue(tracker.try_claim(3))
    self.assertEqual(0.0, tracker.fraction_consumed())
    self.assertTrue(tracker.try_claim(4))
    self.assertEqual(1.0 / 3, tracker.fraction_consumed())
    self.assertTrue(tracker.try_claim(5))
    self.assertEqual(2.0 / 3, tracker.fraction_consumed())
    tracker.set_current_position(6)
    self.assertEqual(1.0, tracker.fraction_consumed())
    tracker.set_current_position(7)
    self.assertFalse(tracker.try_claim(7))

  def test_get_fraction_consumed_sparse(self):
    tracker = range_trackers.OffsetRangeTracker(100, 200)
    self.assertEqual(0, tracker.fraction_consumed())
    self.assertTrue(tracker.try_claim(110))
    # Consumed positions through 110 = total 10 positions of 100 done.
    self.assertEqual(0.10, tracker.fraction_consumed())
    self.assertTrue(tracker.try_claim(150))
    self.assertEqual(0.50, tracker.fraction_consumed())
    self.assertTrue(tracker.try_claim(195))
    self.assertEqual(0.95, tracker.fraction_consumed())

  def test_everything_with_unbounded_range(self):
    tracker = range_trackers.OffsetRangeTracker(
        100,
        range_trackers.OffsetRangeTracker.OFFSET_INFINITY)
    self.assertTrue(tracker.try_claim(150))
    self.assertTrue(tracker.try_claim(250))
    # get_position_for_fraction_consumed should fail for an unbounded range
    with self.assertRaises(Exception):
      tracker.position_at_fraction(0.5)

  def test_try_return_first_record_not_split_point(self):
    with self.assertRaises(Exception):
      range_trackers.OffsetRangeTracker(100, 200).set_current_position(120)

  def test_try_return_record_non_monotonic(self):
    tracker = range_trackers.OffsetRangeTracker(100, 200)
    self.assertTrue(tracker.try_claim(120))
    with self.assertRaises(Exception):
      tracker.try_claim(110)


class GroupedShuffleRangeTrackerTest(unittest.TestCase):

  def bytes_to_position(self, bytes_array):
    return array.array('B', bytes_array).tostring()

  def test_try_return_record_in_infinite_range(self):
    tracker = range_trackers.GroupedShuffleRangeTracker('', '')
    self.assertTrue(tracker.try_claim(
        self.bytes_to_position([1, 2, 3])))
    self.assertTrue(tracker.try_claim(
        self.bytes_to_position([1, 2, 5])))
    self.assertTrue(tracker.try_claim(
        self.bytes_to_position([3, 6, 8, 10])))

  def test_try_return_record_finite_range(self):
    tracker = range_trackers.GroupedShuffleRangeTracker(
        self.bytes_to_position([1, 0, 0]), self.bytes_to_position([5, 0, 0]))
    self.assertTrue(tracker.try_claim(
        self.bytes_to_position([1, 2, 3])))
    self.assertTrue(tracker.try_claim(
        self.bytes_to_position([1, 2, 5])))
    self.assertTrue(tracker.try_claim(
        self.bytes_to_position([3, 6, 8, 10])))
    self.assertTrue(tracker.try_claim(
        self.bytes_to_position([4, 255, 255, 255])))
    # Should fail for positions that are lexicographically equal to or larger
    # than the defined stop position.
    self.assertFalse(copy.copy(tracker).try_claim(
        self.bytes_to_position([5, 0, 0])))
    self.assertFalse(copy.copy(tracker).try_claim(
        self.bytes_to_position([5, 0, 1])))
    self.assertFalse(copy.copy(tracker).try_claim(
        self.bytes_to_position([6, 0, 0])))

  def test_try_return_record_with_non_split_point(self):
    tracker = range_trackers.GroupedShuffleRangeTracker(
        self.bytes_to_position([1, 0, 0]), self.bytes_to_position([5, 0, 0]))
    self.assertTrue(tracker.try_claim(
        self.bytes_to_position([1, 2, 3])))
    tracker.set_current_position(self.bytes_to_position([1, 2, 3]))
    tracker.set_current_position(self.bytes_to_position([1, 2, 3]))
    self.assertTrue(tracker.try_claim(
        self.bytes_to_position([1, 2, 5])))
    tracker.set_current_position(self.bytes_to_position([1, 2, 5]))
    self.assertTrue(tracker.try_claim(
        self.bytes_to_position([3, 6, 8, 10])))
    self.assertTrue(tracker.try_claim(
        self.bytes_to_position([4, 255, 255, 255])))

  def test_first_record_non_split_point(self):
    tracker = range_trackers.GroupedShuffleRangeTracker(
        self.bytes_to_position([3, 0, 0]), self.bytes_to_position([5, 0, 0]))
    with self.assertRaises(ValueError):
      tracker.set_current_position(self.bytes_to_position([3, 4, 5]))

  def test_non_split_point_record_with_different_position(self):
    tracker = range_trackers.GroupedShuffleRangeTracker(
        self.bytes_to_position([3, 0, 0]), self.bytes_to_position([5, 0, 0]))
    self.assertTrue(tracker.try_claim(self.bytes_to_position([3, 4, 5])))
    with self.assertRaises(ValueError):
      tracker.set_current_position(self.bytes_to_position([3, 4, 6]))

  def test_try_return_record_before_start(self):
    tracker = range_trackers.GroupedShuffleRangeTracker(
        self.bytes_to_position([3, 0, 0]), self.bytes_to_position([5, 0, 0]))
    with self.assertRaises(ValueError):
      tracker.try_claim(self.bytes_to_position([1, 2, 3]))

  def test_try_return_non_monotonic(self):
    tracker = range_trackers.GroupedShuffleRangeTracker(
        self.bytes_to_position([3, 0, 0]), self.bytes_to_position([5, 0, 0]))
    self.assertTrue(tracker.try_claim(self.bytes_to_position([3, 4, 5])))
    self.assertTrue(tracker.try_claim(self.bytes_to_position([3, 4, 6])))
    with self.assertRaises(ValueError):
      tracker.try_claim(self.bytes_to_position([3, 2, 1]))

  def test_try_return_identical_positions(self):
    tracker = range_trackers.GroupedShuffleRangeTracker(
        self.bytes_to_position([3, 0, 0]), self.bytes_to_position([5, 0, 0]))
    self.assertTrue(tracker.try_claim(
        self.bytes_to_position([3, 4, 5])))
    with self.assertRaises(ValueError):
      tracker.try_claim(self.bytes_to_position([3, 4, 5]))

  def test_try_split_at_position_infinite_range(self):
    tracker = range_trackers.GroupedShuffleRangeTracker('', '')
    # Should fail before first record is returned.
    self.assertFalse(tracker.try_split(
        self.bytes_to_position([3, 4, 5, 6])))

    self.assertTrue(tracker.try_claim(
        self.bytes_to_position([1, 2, 3])))

    # Should now succeed.
    self.assertIsNotNone(tracker.try_split(
        self.bytes_to_position([3, 4, 5, 6])))
    # Should not split at same or larger position.
    self.assertIsNone(tracker.try_split(
        self.bytes_to_position([3, 4, 5, 6])))
    self.assertIsNone(tracker.try_split(
        self.bytes_to_position([3, 4, 5, 6, 7])))
    self.assertIsNone(tracker.try_split(
        self.bytes_to_position([4, 5, 6, 7])))

    # Should split at smaller position.
    self.assertIsNotNone(tracker.try_split(
        self.bytes_to_position([3, 2, 1])))

    self.assertTrue(tracker.try_claim(
        self.bytes_to_position([2, 3, 4])))

    # Should not split at a position we're already past.
    self.assertIsNone(tracker.try_split(
        self.bytes_to_position([2, 3, 4])))
    self.assertIsNone(tracker.try_split(
        self.bytes_to_position([2, 3, 3])))

    self.assertTrue(tracker.try_claim(
        self.bytes_to_position([3, 2, 0])))
    self.assertFalse(tracker.try_claim(
        self.bytes_to_position([3, 2, 1])))

  def test_try_test_split_at_position_finite_range(self):
    tracker = range_trackers.GroupedShuffleRangeTracker(
        self.bytes_to_position([0, 0, 0]),
        self.bytes_to_position([10, 20, 30]))
    # Should fail before first record is returned.
    self.assertFalse(tracker.try_split(
        self.bytes_to_position([0, 0, 0])))
    self.assertFalse(tracker.try_split(
        self.bytes_to_position([3, 4, 5, 6])))

    self.assertTrue(tracker.try_claim(
        self.bytes_to_position([1, 2, 3])))

    # Should now succeed.
    self.assertTrue(tracker.try_split(
        self.bytes_to_position([3, 4, 5, 6])))
    # Should not split at same or larger position.
    self.assertFalse(tracker.try_split(
        self.bytes_to_position([3, 4, 5, 6])))
    self.assertFalse(tracker.try_split(
        self.bytes_to_position([3, 4, 5, 6, 7])))
    self.assertFalse(tracker.try_split(
        self.bytes_to_position([4, 5, 6, 7])))

    # Should split at smaller position.
    self.assertTrue(tracker.try_split(
        self.bytes_to_position([3, 2, 1])))
    # But not at a position at or before last returned record.
    self.assertFalse(tracker.try_split(
        self.bytes_to_position([1, 2, 3])))

    self.assertTrue(tracker.try_claim(
        self.bytes_to_position([2, 3, 4])))
    self.assertTrue(tracker.try_claim(
        self.bytes_to_position([3, 2, 0])))
    self.assertFalse(tracker.try_claim(
        self.bytes_to_position([3, 2, 1])))


class OrderedPositionRangeTrackerTest(unittest.TestCase):

  class DoubleRangeTracker(range_trackers.OrderedPositionRangeTracker):

    @staticmethod
    def fraction_to_position(fraction, start, end):
      return start + (end - start) * fraction

    @staticmethod
    def position_to_fraction(pos, start, end):
      return float(pos - start) / (end - start)

  def test_try_claim(self):
    tracker = self.DoubleRangeTracker(10, 20)
    self.assertTrue(tracker.try_claim(10))
    self.assertTrue(tracker.try_claim(15))
    self.assertFalse(tracker.try_claim(20))
    self.assertFalse(tracker.try_claim(25))

  def test_fraction_consumed(self):
    tracker = self.DoubleRangeTracker(10, 20)
    self.assertEqual(0, tracker.fraction_consumed())
    tracker.try_claim(10)
    self.assertEqual(0, tracker.fraction_consumed())
    tracker.try_claim(15)
    self.assertEqual(.5, tracker.fraction_consumed())
    tracker.try_claim(17)
    self.assertEqual(.7, tracker.fraction_consumed())
    tracker.try_claim(25)
    self.assertEqual(.7, tracker.fraction_consumed())

  def test_try_split(self):
    tracker = self.DoubleRangeTracker(10, 20)
    tracker.try_claim(15)
    self.assertEqual(.5, tracker.fraction_consumed())
    # Split at 18.
    self.assertEqual((18, 0.8), tracker.try_split(18))
    # Fraction consumed reflects smaller range.
    self.assertEqual(.625, tracker.fraction_consumed())
    # We can claim anything less than 18,
    self.assertTrue(tracker.try_claim(17))
    # but can't split before claimed 17,
    self.assertIsNone(tracker.try_split(16))
    # nor claim anything at or after 18.
    self.assertFalse(tracker.try_claim(18))
    self.assertFalse(tracker.try_claim(19))

  def test_claim_order(self):
    tracker = self.DoubleRangeTracker(10, 20)
    tracker.try_claim(12)
    tracker.try_claim(15)
    with self.assertRaises(ValueError):
      tracker.try_claim(13)

  def test_out_of_range(self):
    tracker = self.DoubleRangeTracker(10, 20)
    # Can't claim before range.
    with self.assertRaises(ValueError):
      tracker.try_claim(-5)
    # Can't split before range.
    with self.assertRaises(ValueError):
      tracker.try_split(-5)
    # Reject useless split at start position.
    with self.assertRaises(ValueError):
      tracker.try_split(10)
    # Can't split after range.
    with self.assertRaises(ValueError):
      tracker.try_split(25)
    tracker.try_split(15)
    # Can't split after modified range.
    with self.assertRaises(ValueError):
      tracker.try_split(17)
    # Reject useless split at end position.
    with self.assertRaises(ValueError):
      tracker.try_split(15)
    self.assertTrue(tracker.try_split(14))


class UnsplittableRangeTrackerTest(unittest.TestCase):

  def test_try_claim(self):
    tracker = range_trackers.UnsplittableRangeTracker(
        range_trackers.OffsetRangeTracker(100, 200))
    self.assertTrue(tracker.try_claim(110))
    self.assertTrue(tracker.try_claim(140))
    self.assertTrue(tracker.try_claim(183))
    self.assertFalse(tracker.try_claim(210))

  def test_try_split_fails(self):
    tracker = range_trackers.UnsplittableRangeTracker(
        range_trackers.OffsetRangeTracker(100, 200))
    self.assertTrue(tracker.try_claim(110))
    # Out of range
    self.assertFalse(tracker.try_split(109))
    self.assertFalse(tracker.try_split(210))

    # Within range. But splitting is still unsuccessful.
    self.assertFalse(copy.copy(tracker).try_split(111))
    self.assertFalse(copy.copy(tracker).try_split(130))
    self.assertFalse(copy.copy(tracker).try_split(199))


class LexicographicKeyRangeTrackerTest(unittest.TestCase):
  """
  Tests of LexicographicKeyRangeTracker.
  """

  key_to_fraction = (
      range_trackers.LexicographicKeyRangeTracker.position_to_fraction)
  fraction_to_key = (
      range_trackers.LexicographicKeyRangeTracker.fraction_to_position)

  def _check(self, fraction=None, key=None, start=None, end=None, delta=0):
    assert key is not None or fraction is not None
    if fraction is None:
      fraction = self.key_to_fraction(key, start, end)
    elif key is None:
      key = self.fraction_to_key(fraction, start, end)

    if key is None and end is None and fraction == 1:
      # No way to distinguish from fraction == 0.
      computed_fraction = 1
    else:
      computed_fraction = self.key_to_fraction(key, start, end)
    computed_key = self.fraction_to_key(fraction, start, end)

    if delta:
      self.assertAlmostEqual(computed_fraction, fraction,
                             delta=delta, places=None, msg=str(locals()))
    else:
      self.assertEqual(computed_fraction, fraction, str(locals()))
    self.assertEqual(computed_key, key, str(locals()))

  def test_key_to_fraction_no_endpoints(self):
    self._check(key='\x07', fraction=7/256.)
    self._check(key='\xFF', fraction=255/256.)
    self._check(key='\x01\x02\x03', fraction=(2**16 + 2**9 + 3) / (2.0**24))

  def test_key_to_fraction(self):
    self._check(key='\x87', start='\x80', fraction=7/128.)
    self._check(key='\x07', end='\x10', fraction=7/16.)
    self._check(key='\x47', start='\x40', end='\x80', fraction=7/64.)
    self._check(key='\x47\x80', start='\x40', end='\x80', fraction=15/128.)

  def test_key_to_fraction_common_prefix(self):
    self._check(
        key='a' * 100 + 'b', start='a' * 100 + 'a', end='a' * 100 + 'c',
        fraction=0.5)
    self._check(
        key='a' * 100 + 'b', start='a' * 100 + 'a', end='a' * 100 + 'e',
        fraction=0.25)
    self._check(
        key='\xFF' * 100 + '\x40', start='\xFF' * 100, end=None, fraction=0.25)
    self._check(key='foob',
                start='fooa\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFE',
                end='foob\x00\x00\x00\x00\x00\x00\x00\x00\x02',
                fraction=0.5)

  def test_tiny(self):
    self._check(fraction=.5**20, key='\0\0\x10')
    self._check(fraction=.5**20, start='a', end='b', key='a\0\0\x10')
    self._check(fraction=.5**20, start='a', end='c', key='a\0\0\x20')
    self._check(fraction=.5**20, start='xy_a', end='xy_c', key='xy_a\0\0\x20')
    self._check(fraction=.5**20, start='\xFF\xFF\x80',
                key='\xFF\xFF\x80\x00\x08')
    self._check(fraction=.5**20 / 3,
                start='xy_a',
                end='xy_c',
                key='xy_a\x00\x00\n\xaa\xaa\xaa\xaa\xaa',
                delta=1e-15)
    self._check(fraction=.5**100, key='\0' * 12 + '\x10')

  def test_lots(self):
    for fraction in (0, 1, .5, .75, 7./512, 1 - 7./4096):
      self._check(fraction)
      self._check(fraction, start='\x01')
      self._check(fraction, end='\xF0')
      self._check(fraction, start='0x75', end='\x76')
      self._check(fraction, start='0x75', end='\x77')
      self._check(fraction, start='0x75', end='\x78')
      self._check(fraction, start='a' * 100 + '\x80', end='a' * 100 + '\x81')
      self._check(fraction, start='a' * 101 + '\x80', end='a' * 101 + '\x81')
      self._check(fraction, start='a' * 102 + '\x80', end='a' * 102 + '\x81')
    for fraction in (.3, 1/3., 1/math.e, .001, 1e-30, .99, .999999):
      self._check(fraction, delta=1e-14)
      self._check(fraction, start='\x01', delta=1e-14)
      self._check(fraction, end='\xF0', delta=1e-14)
      self._check(fraction, start='0x75', end='\x76', delta=1e-14)
      self._check(fraction, start='0x75', end='\x77', delta=1e-14)
      self._check(fraction, start='0x75', end='\x78', delta=1e-14)
      self._check(fraction, start='a' * 100 + '\x80', end='a' * 100 + '\x81',
                  delta=1e-14)

  def test_good_prec(self):
    # There should be about 7 characters (~53 bits) of precision
    # (beyond the common prefix of start and end).
    self._check(1 / math.e, start='abc_abc', end='abc_xyz',
                key='abc_i\xe0\xf4\x84\x86\x99\x96',
                delta=1e-15)
    # This remains true even if the start and end keys are given to
    # high precision.
    self._check(1 / math.e,
                start='abcd_abc\0\0\0\0\0_______________abc',
                end='abcd_xyz\0\0\0\0\0\0_______________abc',
                key='abcd_i\xe0\xf4\x84\x86\x99\x96',
                delta=1e-15)
    # For very small fractions, however, higher precision is used to
    # accurately represent small increments in the keyspace.
    self._check(1e-20 / math.e, start='abcd_abc', end='abcd_xyz',
                key='abcd_abc\x00\x00\x00\x00\x00\x01\x91#\x172N\xbb',
                delta=1e-35)


if __name__ == '__main__':
  logging.getLogger().setLevel(logging.INFO)
  unittest.main()
