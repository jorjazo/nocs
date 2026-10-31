// The little of Node's test runner the unit tests use (`pnpm test`). Declared
// here rather than with @types/node, whose globals (setTimeout returning an
// object, `process`) would leak into the browser code's types.

declare module "node:test" {
  export function test(name: string, run: () => void | Promise<void>): void;
}

declare module "node:assert/strict" {
  const assert: {
    (value: unknown, message?: string): asserts value;
    equal<T>(actual: unknown, expected: T, message?: string): asserts actual is T;
    deepEqual<T>(actual: unknown, expected: T, message?: string): asserts actual is T;
    ok(value: unknown, message?: string): asserts value;
    throws(run: () => unknown, message?: string): void;
  };
  export default assert;
}
