import "@testing-library/jest-dom/vitest";

// jsdom ships no observer APIs; Arc components measure with them. Stubs that
// report "nothing changed" are enough for behavior tests (no visual asserts).
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
class IntersectionObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return [];
  }
}
window.ResizeObserver = window.ResizeObserver ?? (ResizeObserverStub as unknown as typeof ResizeObserver);
window.IntersectionObserver =
  window.IntersectionObserver ?? (IntersectionObserverStub as unknown as typeof IntersectionObserver);
