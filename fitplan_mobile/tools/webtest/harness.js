// TEST-ONLY entry: renders the real App.js in a browser with the stand-ins above.
import React from "react";
import { createRoot } from "react-dom/client";
import App from "../../App";

createRoot(document.getElementById("root")).render(<App />);
