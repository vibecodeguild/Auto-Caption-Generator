import assert from "node:assert/strict";
import test from "node:test";

import {
  beginPreviewRequest,
  isCurrentPreviewRequest,
  playMediaAt,
} from "../../web/lib/media-preview.ts";

test("playMediaAt seeks before requesting playback without waiting for seeked", async () => {
  const calls: string[] = [];
  let currentTime = 0;
  const video = {
    readyState: 1,
    get currentTime() {
      return currentTime;
    },
    set currentTime(value: number) {
      currentTime = value;
      calls.push(`seek:${value}`);
    },
    play() {
      calls.push("play");
      return Promise.resolve();
    },
  } as HTMLMediaElement;

  const playback = playMediaAt(video, 12.5);

  assert.deepEqual(calls, ["seek:12.5", "play"]);
  await playback;
});

test("a newer preview request invalidates delayed work from the prior click", () => {
  const counter = { current: 0 };
  const first = beginPreviewRequest(counter);
  const second = beginPreviewRequest(counter);

  assert.equal(isCurrentPreviewRequest(counter, first), false);
  assert.equal(isCurrentPreviewRequest(counter, second), true);
});

test("playMediaAt reports a source that has not loaded metadata", async () => {
  const video = {
    readyState: 0,
    currentTime: 0,
    play: () => Promise.resolve(),
  } as HTMLMediaElement;

  await assert.rejects(
    playMediaAt(video, 2),
    /source video is still loading/i,
  );
});
