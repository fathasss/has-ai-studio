const sqlite3 = require('sqlite3').verbose();
const db = new sqlite3.Database('./database.db');

// Function to create table if not exists
async function createTable() {
  try {
    await db.run(`
      CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        description TEXT NOT NULL,
        amount REAL NOT NULL,
        date DATE NOT NULL DEFAULT CURRENT_DATE
      );
    `);
  } catch (err) {
    console.error(err);
  }
}

// Function to insert expense
async function insertExpense(req, res) {
  try {
    const { description, amount } = req.body;
    if (!description || !amount) {
      return res.status(400).send({ error: 'Please provide description and amount' });
    }

    await db.run('INSERT INTO expenses (description, amount) VALUES (?, ?)', description, amount);
    return res.send({ message: 'Expense added successfully' });
  } catch (err) {
    console.error(err);
    return res.status(500).send({ error: 'Error adding expense' });
  }
}

// Function to get all expenses
async function getAllExpenses(req, res) {
  try {
    const results = await db.all('SELECT * FROM expenses');
    if (results.length === 0) {
      return res.send([]);
    }

    return res.send(results);
  } catch (err) {
    console.error(err);
    return res.status(500).send({ error: 'Error fetching expenses' });
  }
}

module.exports = { createTable, insertExpense, getAllExpenses };