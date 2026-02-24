const express = require('express');
const router = express.Router();
const { insertExpense, getAllExpenses } = require('../controllers/expenseController');

router.post('/expenses', (req, res) => {
  insertExpense(req, res).catch(err => console.error(err));
});

router.get('/expenses', (req, res) => {
  getAllExpenses(req, res).catch(err => console.error(err));
});

module.exports = router;