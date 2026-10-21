import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("project foundation page", () => {
  it("identifies itself as a foundation placeholder", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "GPU Resource Marketplace" })).toBeInTheDocument();
    expect(screen.getByText("Development preview", { selector: ".status" })).toBeInTheDocument();
  });
});
