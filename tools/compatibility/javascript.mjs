// Select syntax nodes rather than guessing where a function's braces end.
import { parse } from "acorn";

export function parseSource(source) {
  const options = { ecmaVersion: "latest", locations: true };
  try {
    return parse(source, { ...options, sourceType: "script" });
  } catch {
    return parse(source, { ...options, sourceType: "module" });
  }
}

export function* walk(node) {
  if (!node || typeof node !== "object") return;
  if (typeof node.type === "string") yield node;
  for (const [key, value] of Object.entries(node)) {
    if (key === "loc") continue;
    if (Array.isArray(value)) {
      for (const child of value) yield* walk(child);
    } else if (value && typeof value === "object") {
      yield* walk(value);
    }
  }
}

export function memberPath(node) {
  if (!node) return null;
  if (node.type === "ChainExpression") return memberPath(node.expression);
  if (node.type === "Identifier") return node.name;
  if (node.type === "ThisExpression") return "this";
  if (node.type === "MemberExpression") {
    const property = node.computed ? node.property.value : node.property.name;
    const parent = memberPath(node.object);
    return parent && typeof property === "string" ? `${parent}.${property}` : null;
  }
  return null;
}

export function functions(ast) {
  const found = [];
  for (const node of walk(ast)) {
    if (node.type === "AssignmentExpression" && isFunction(node.right)) {
      found.push({ selector: memberPath(node.left), node: node.right });
    } else if (node.type === "Property" && isFunction(node.value)) {
      found.push({ selector: node.computed ? node.key.value : node.key.name ?? node.key.value, node: node.value });
    } else if (node.type === "FunctionDeclaration") {
      found.push({ selector: node.id.name, node });
    } else if (node.type === "VariableDeclarator" && isFunction(node.init)) {
      found.push({ selector: memberPath(node.id), node: node.init });
    }
  }
  return found;
}

function isFunction(node) {
  return node && ["FunctionExpression", "ArrowFunctionExpression"].includes(node.type);
}

export function extractFunction(source, selector) {
  const matches = functions(parseSource(source)).filter(entry => entry.selector === selector);
  if (matches.length !== 1) {
    throw new Error(`Expected exactly one function for ${selector}; found ${matches.length}`);
  }
  const node = matches[0].node;
  // Object method shorthand starts at its argument list, not at 'function'.
  let expression = source.slice(node.start, node.end);
  if (node.type === "FunctionExpression" && !/^(?:async\s+)?function\b/.test(expression)) {
    expression = `${node.async ? "async " : ""}function${node.generator ? "*" : ""} ${expression}`;
  }
  return { source: expression, line: node.loc.start.line, parameters: node.params.map(p => source.slice(p.start, p.end)) };
}
