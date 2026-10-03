import { readFileSync } from "node:fs";
import vm from "node:vm";
import { extractFunction } from "./javascript.mjs";
import { adapterScript } from "./adapters.mjs";
import { indexSource } from "./index_client.mjs";
import { networkInventory } from "./network.mjs";

try {
  const request = JSON.parse(readFileSync(0, "utf8"));
  let result;
  if (request.operation === "network") {
    result = networkInventory(request.files);
  } else if (request.operation === "index") {
    result = indexSource(request.source);
  } else if (request.operation === "extract") {
    result = extractFunction(request.source, request.selector);
  } else if (request.operation === "call") {
    const selected = extractFunction(request.source, request.selector);
    // vm isolates fixture globals. The process timeout also covers pending promises.
    const dependencies = Object.entries(request.dependencies ?? {}).map(([name, definition]) =>
      `${JSON.stringify(name)}: (${extractFunction(definition.source, definition.selector).source})`,
    ).join(",");
    const context = vm.createContext({
      serializedArgs: JSON.stringify(request.args),
      serializedFixtures: JSON.stringify(request.fixtures ?? {}),
    });
    result = await vm.runInContext(
      `const selected = (${selected.source});
       const args = JSON.parse(serializedArgs);
       const fixtures = JSON.parse(serializedFixtures);
       const dependencies = {${dependencies}};
       ${adapterScript(request.adapter ?? "pure")}`, context, { timeout: 1000 },
    );
  } else {
    throw new Error(`Unknown operation: ${request.operation}`);
  }
  process.stdout.write(JSON.stringify(result ?? null));
} catch (error) {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
}
