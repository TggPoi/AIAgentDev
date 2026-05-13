const forbidden = /\b(CREATE|MERGE|SET|DELETE|DETACH|DROP|REMOVE)\b/i;

const cypher = process.argv.slice(2).join(" ");
if (!cypher.trim()) {
  console.error("Usage: node validate-readonly-cypher.mjs '<cypher>'");
  process.exit(2);
}

if (forbidden.test(cypher)) {
  console.error("Unsafe Cypher: write operation detected.");
  process.exit(1);
}

console.log("OK: read-only Cypher.");
