export const CHAT_BOTTOM_THRESHOLD_PX = 80;
export const CHAT_PAGE_SCROLL_RATIO = 0.85;

const SCROLL_BOUNDARY_TOLERANCE_PX = 1;

export interface ChatScrollMetrics {
  scrollTop: number;
  scrollHeight: number;
  clientHeight: number;
}

export interface ChatScrollState {
  hasOverflow: boolean;
  canScrollUp: boolean;
  canScrollDown: boolean;
  isNearBottom: boolean;
}

export type ChatScrollDirection = 'previous' | 'next';

export function getChatScrollState({
  scrollTop,
  scrollHeight,
  clientHeight,
}: ChatScrollMetrics): ChatScrollState {
  const maximumScrollTop = Math.max(0, scrollHeight - clientHeight);
  const normalizedScrollTop = Math.min(
    maximumScrollTop,
    Math.max(0, scrollTop),
  );
  const distanceFromBottom = maximumScrollTop - normalizedScrollTop;
  const hasOverflow = maximumScrollTop > SCROLL_BOUNDARY_TOLERANCE_PX;

  return {
    hasOverflow,
    canScrollUp:
      hasOverflow && normalizedScrollTop > SCROLL_BOUNDARY_TOLERANCE_PX,
    canScrollDown:
      hasOverflow && distanceFromBottom > SCROLL_BOUNDARY_TOLERANCE_PX,
    isNearBottom: distanceFromBottom <= CHAT_BOTTOM_THRESHOLD_PX,
  };
}

export function getPageScrollDelta(
  clientHeight: number,
  direction: ChatScrollDirection,
): number {
  const distance = Math.max(
    1,
    Math.round(Math.max(0, clientHeight) * CHAT_PAGE_SCROLL_RATIO),
  );

  return direction === 'previous' ? -distance : distance;
}
