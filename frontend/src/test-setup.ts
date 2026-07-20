import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Without `globals: true`, React Testing Library never registers its automatic
// afterEach cleanup, so each test's render leaks into document.body and the
// next test's `screen` queries hit stale DOM (a flaky ambiguous-match race).
// Register it explicitly.
afterEach(cleanup);
