import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Badge, countdown } from "../components/ui";

describe("Badge", () => {
  it("renders the reality class and label", () => {
    const { container } = render(<Badge kind="verified" />);
    expect(container.querySelector(".badge.verified")).toBeInTheDocument();
    expect(screen.getByText("verified")).toBeInTheDocument();
  });
});

describe("countdown", () => {
  it("formats minutes, hours, days and past times", () => {
    expect(countdown(90)).toBe("1m");
    expect(countdown(3 * 3600 + 20 * 60)).toBe("3h 20m");
    expect(countdown(2 * 86400 + 5 * 3600)).toBe("2d 5h");
    expect(countdown(-120).startsWith("-")).toBe(true);
    expect(countdown(null)).toBe("");
  });
});
