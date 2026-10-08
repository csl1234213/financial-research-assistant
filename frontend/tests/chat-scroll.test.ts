import assert from 'node:assert/strict';
import test from 'node:test';
import {
  CHAT_BOTTOM_THRESHOLD_PX,
  CHAT_PAGE_SCROLL_RATIO,
  getChatScrollState,
  getPageScrollDelta,
} from '../src/components/chat/chatScroll.ts';

test('content shorter than the viewport does not expose scroll controls', () => {
  assert.deepEqual(
    getChatScrollState({
      scrollTop: 0,
      scrollHeight: 500,
      clientHeight: 600,
    }),
    {
      hasOverflow: false,
      canScrollUp: false,
      canScrollDown: false,
      isNearBottom: true,
    },
  );
});

test('top, middle, and bottom expose the correct navigation states', () => {
  const metrics = {
    scrollHeight: 1_600,
    clientHeight: 600,
  };

  assert.deepEqual(getChatScrollState({ ...metrics, scrollTop: 0 }), {
    hasOverflow: true,
    canScrollUp: false,
    canScrollDown: true,
    isNearBottom: false,
  });
  assert.deepEqual(getChatScrollState({ ...metrics, scrollTop: 500 }), {
    hasOverflow: true,
    canScrollUp: true,
    canScrollDown: true,
    isNearBottom: false,
  });
  assert.deepEqual(getChatScrollState({ ...metrics, scrollTop: 1_000 }), {
    hasOverflow: true,
    canScrollUp: true,
    canScrollDown: false,
    isNearBottom: true,
  });
});

test('near-bottom tracking uses the configured reader threshold', () => {
  const metrics = {
    scrollHeight: 1_600,
    clientHeight: 600,
  };

  assert.equal(
    getChatScrollState({
      ...metrics,
      scrollTop: 1_000 - CHAT_BOTTOM_THRESHOLD_PX,
    }).isNearBottom,
    true,
  );
  assert.equal(
    getChatScrollState({
      ...metrics,
      scrollTop: 999 - CHAT_BOTTOM_THRESHOLD_PX,
    }).isNearBottom,
    false,
  );
});

test('page controls move by 85 percent of the visible viewport', () => {
  const viewportHeight = 600;
  const expectedDistance = Math.round(
    viewportHeight * CHAT_PAGE_SCROLL_RATIO,
  );

  assert.equal(getPageScrollDelta(viewportHeight, 'previous'), -expectedDistance);
  assert.equal(getPageScrollDelta(viewportHeight, 'next'), expectedDistance);
});
