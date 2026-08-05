import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";

const mount = document.getElementById("root");
if (mount) createRoot(mount).render(<App />);
