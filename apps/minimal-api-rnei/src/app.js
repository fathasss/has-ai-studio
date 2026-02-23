// Import required dependencies
const express = require('express');

// Initialize Express.js application
const app = express();

// Define a route for the GET request
app.get('/get', (req, res) => {
  // Send 'Hello World!' as a response to the client
  res.send('Hello World!');
});

// Set server port and start listening on it
const port = 3000;
app.listen(port, () => {
  console.log(`Server is running on port ${port}`);
});