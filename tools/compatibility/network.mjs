// Enumerate call sites over the whole AST, including unassigned callbacks.
import { functions, memberPath, parseSource, walk } from "./javascript.mjs";

export function networkInventory(files) {
  const calls = [], errors = [];
  for (const {file, source} of files) {
    try {
      const ast = parseSource(source);
      const named = functions(ast).filter(entry => entry.selector);
      const nodes = [...walk(ast)];
      const frames = new WeakMap();
      function visit(node, frame) {
        if (!node || typeof node !== "object") return;
        if (node.type === "Program" || node.type === "BlockStatement" || /Function/.test(node.type ?? "")) {
          frame = {parent: frame, values: new Map(), writes: new Set()};
          for (const parameter of node.params ?? []) if (parameter.type === "Identifier") frame.values.set(parameter.name, null);
        }
        frames.set(node, frame);
        if (node.type === "VariableDeclarator" && node.id.type === "Identifier") {
          frame.values.set(node.id.name, frame.values.has(node.id.name) ? null : node.init);
        }
        if (["AssignmentExpression", "UpdateExpression"].includes(node.type)) {
          const target = node.left ?? node.argument;
          if (target.type === "Identifier") {
            // Conservatively invalidate assignments, even in an inner scope.
            for (let current = frame; current; current = current.parent) current.writes.add(target.name);
          }
        }
        for (const [key, value] of Object.entries(node)) {
          if (key === "loc") continue;
          if (Array.isArray(value)) for (const child of value) visit(child, frame);
          else if (value && typeof value === "object") visit(value, frame);
        }
      }
      visit(ast, null);
      const text = node => source.slice(node.start, node.end);
      for (const node of nodes) {
        if (!["CallExpression", "NewExpression"].includes(node.type)) continue;
        const callee = memberPath(node.callee) ?? "";
        const transport = callee.split(".").at(-1);
        const xhrOpen = transport === "open" && /(?:xmlhttp|xhr|request)\.open$/i.test(callee);
        if (!(["makeRequest", "request", "download", "doGet", "doPost", "fetch",
          "WebSocket", "XMLHttpRequest", "newChannel", "newChannelFromURI", "asyncFetch"].includes(transport) || xhrOpen)) continue;
        const enclosing = named.filter(entry => entry.node.start <= node.start && entry.node.end >= node.end)
          .sort((a, b) => (a.node.end - a.node.start) - (b.node.end - b.node.start))[0];
        function template(value, seen = new Set(), frame = frames.get(node)) {
          if (!value) return "{unresolved}";
          if (value.type === "Literal") return String(value.value);
          if (value.type === "BinaryExpression" && value.operator === "+") return template(value.left, seen, frame) + template(value.right, seen, frame);
          if (value.type === "TemplateLiteral") return value.quasis.map((part, i) => part.value.cooked + (value.expressions[i] ? template(value.expressions[i], seen, frame) : "")).join("");
          if (value.type === "Identifier" && !seen.has(value.name)) {
            for (let scope = frame; scope; scope = scope.parent) {
              if (!scope.values.has(value.name)) continue;
              if (scope.values.get(value.name) && !scope.writes.has(value.name)) return template(scope.values.get(value.name), new Set([...seen, value.name]), scope);
              break;
            }
          }
          return `{${text(value)}}`;
        }
        const methodArgument = ["makeRequest", "request"].includes(transport) || xhrOpen;
        const method = transport === "XMLHttpRequest" ? "{xhr.open}" : methodArgument ? template(node.arguments[0]) : transport === "doPost" ? "POST" : transport === "WebSocket" ? "WS" : transport === "fetch" ? "{options.method ?? GET}" : "GET";
        calls.push({file, selector: enclosing?.selector ?? "<top-level>", line: node.loc.start.line,
          transport, method, uri: template(node.arguments[methodArgument ? 1 : 0]), expression: text(node)});
      }
    } catch (error) { errors.push({file, error: error.message}); }
  }
  return {calls, errors};
}
