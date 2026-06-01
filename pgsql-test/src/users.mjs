import { query } from "./db.mjs";

async function createUser(name) {
  const { rows } = await query(
    "INSERT INTO users (name) VALUES ($1) RETURNING *",
    [name]
  );
  return rows[0];
}

async function getUserById(id) {
  const { rows } = await query("SELECT * FROM users WHERE id = $1", [id]);
  return rows[0] ?? null;
}

async function getAllUsers() {
  const { rows } = await query("SELECT * FROM users ORDER BY id");
  return rows;
}

async function updateUser(id, name) {
  const { rows } = await query(
    "UPDATE users SET name = $1 WHERE id = $2 RETURNING *",
    [name, id]
  );
  return rows[0] ?? null;
}

async function deleteUser(id) {
  const { rowCount } = await query("DELETE FROM users WHERE id = $1", [id]);
  return rowCount > 0;
}

export {
  createUser,
  getUserById,
  getAllUsers,
  updateUser,
  deleteUser,
};