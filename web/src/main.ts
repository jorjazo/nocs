import { mount } from "svelte";
import "./app.css";
import App from "./App.svelte";
import { live } from "./lib/live.svelte";

live.start();

const target = document.getElementById("app");
if (!target) throw new Error("missing #app");

export default mount(App, { target });
