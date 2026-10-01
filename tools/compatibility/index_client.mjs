// A syntactic inventory, with source positions and unresolved expressions intact.
import { functions, memberPath, parseSource, walk } from "./javascript.mjs";

export function indexSource(source) {
  return functions(parseSource(source)).filter(entry => entry.selector).map(({ selector, node }) => {
    const nodes = [...walk(node.body)];
    const parameters = node.params.filter(p => p.type === "Identifier").map(p => p.name);
    const aliases = new Map(parameters.map(name => [name, {root: name, path: []}]));
    const values = new Map(nodes.filter(n => n.type === "VariableDeclarator" && n.id.type === "Identifier")
      .map(n => [n.id.name, n.init]));
    function inputPath(expression) {
      const path = memberPath(expression)?.split(".");
      if (!path || !aliases.has(path[0])) return null;
      const alias = aliases.get(path[0]);
      return {root: alias.root, path: [...alias.path, ...path.slice(1)]};
    }
    // Simple aliases can be declared before the variable they refer to.
    for (let pass = 0; pass < values.size; pass++) {
      for (const [name, value] of values) {
        if (value && !aliases.has(name)) {
          const path = inputPath(value);
          if (path) aliases.set(name, path);
        }
      }
    }
    const calls = nodes.filter(n => n.type === "CallExpression");
    const methods = new Set(calls.map(n => n.callee));
    const writes = new Set(nodes.filter(n => n.type === "AssignmentExpression").map(n => n.left));
    const reads = nodes.filter(n => n.type === "MemberExpression" && !methods.has(n) && !writes.has(n))
      .map(n => ({node: n, input: inputPath(n)})).filter(({input}) => input?.path.length)
      .map(({node: n, input}) => ({root: input.root, field: input.path[0], path: input.path.join("."), line: n.loc.start.line}));
    const text = n => source.slice(n.start, n.end);
    function template(expression, seen = new Set()) {
      if (!expression) return "{unresolved}";
      if (expression.type === "Literal") return String(expression.value);
      if (expression.type === "BinaryExpression" && expression.operator === "+") {
        return template(expression.left, seen) + template(expression.right, seen);
      }
      if (expression.type === "Identifier" && values.has(expression.name) && !seen.has(expression.name)) {
        return template(values.get(expression.name), new Set([...seen, expression.name]));
      }
      return `{${text(expression)}}`;
    }
    const headers = calls.filter(n => memberPath(n.callee)?.endsWith(".getResponseHeader"))
      .map(n => ({name: n.arguments[0]?.type === "Literal" ? n.arguments[0].value : null,
        expression: n.arguments[0] ? text(n.arguments[0]) : "", line: n.loc.start.line}));
    const requests = calls.filter(n => /\.(makeRequest|request)$/.test(memberPath(n.callee) ?? ""))
      .map(n => ({method: template(n.arguments[0]), uri: template(n.arguments[1]),
        expression: text(n), line: n.loc.start.line}));
    const conditions = nodes.filter(n => n.type === "IfStatement" || n.type === "ConditionalExpression")
      .map(n => ({expression: text(n.test), line: n.loc.start.line}));
    const defaults = nodes.filter(n => n.type === "VariableDeclarator" && n.init?.type === "Literal")
      .map(n => ({variable: text(n.id), value: n.init.value, line: n.loc.start.line}));
    const successCodes = nodes.filter(n => n.type === "Property" && (n.key.name ?? n.key.value) === "successCodes")
      .map(n => ({expression: text(n.value), line: n.loc.start.line}));
    return {selector, line: node.loc.start.line, end_line: node.loc.end.line,
      parameters, reads, headers, requests, conditions, defaults, successCodes};
  });
}
