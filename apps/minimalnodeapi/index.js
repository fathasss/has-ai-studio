// Import the Express module
const express = require('express');

// Create an instance of the Express app
const app = express();

// Define a route for '/get' endpoint that returns 'Hello World!'
app.get('/get', (req, res) => {
  res.send('Hello World!');
});

// Start the server on port 3000
const PORT = 3000;
app.listen(PORT, () => console.log(`Server started on port ${PORT}`));