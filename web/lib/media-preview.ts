export type PreviewRequestCounter = {
  current: number;
};

export function beginPreviewRequest(counter: PreviewRequestCounter): number {
  counter.current += 1;
  return counter.current;
}

export function isCurrentPreviewRequest(counter: PreviewRequestCounter, requestId: number): boolean {
  return counter.current === requestId;
}

export function playMediaAt(video: HTMLMediaElement, time: number): Promise<void> {
  if (!Number.isFinite(time) || time < 0) {
    return Promise.reject(new Error(`Invalid preview time: ${time}`));
  }
  if (video.readyState < 1) {
    return Promise.reject(new Error("The source video is still loading. Try the preview again."));
  }

  try {
    // Assign the seek before play(), in the initiating click stack. Waiting for a
    // seeked event here can strand playback when Chromium coalesces rapid seeks.
    video.currentTime = time;
    return video.play();
  } catch (error) {
    return Promise.reject(error);
  }
}
