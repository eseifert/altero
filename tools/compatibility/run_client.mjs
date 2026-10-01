import { readFileSync } from "node:fs";
import vm from "node:vm";
import { extractFunction } from "./javascript.mjs";

try {
  const request = JSON.parse(readFileSync(0, "utf8"));
  const selected = extractFunction(request.source, request.selector);
  let result;
  if (request.operation === "extract") {
    result = selected;
  } else if (request.operation === "call") {
    // vm isolates fixture globals. The process timeout also covers pending promises.
    const context = vm.createContext({ serializedArgs: JSON.stringify(request.args) });
    result = await vm.runInContext(
      `(${selected.source})(...JSON.parse(serializedArgs))`, context, { timeout: 1000 },
    );
  } else {
    throw new Error(`Unknown operation: ${request.operation}`);
  }
  process.stdout.write(JSON.stringify(result ?? null));
} catch (error) {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
}
