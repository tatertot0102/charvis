import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { Approvals, Hero, Today } from "../components/sections";
import type { ApprovalSummary, DashboardSection, HeroState, TodayState } from "../types";

const meta: DashboardSection = { id: "today", visible: true, collapsed: false, size: "md", order: 0 };

describe("Today section", () => {
  it("labels calendar / remembered / email realities separately", () => {
    const today: TodayState = {
      events: [{ title: "Interview", when: null, detail: null, badge: "verified" }],
      commitments: [{ title: "ECE Lab", badge: "remembered" }],
      email_events: [{ title: "Invite from Dana", badge: "likely" }],
      conflicts: ["You told me weekdays 10-2 but calendar can't confirm."],
      missing_calendar: [],
    };
    render(<Today meta={meta} today={today} />);
    expect(screen.getByText(/Google Calendar/i)).toBeInTheDocument();
    expect(screen.getByText(/Remembered commitments/i)).toBeInTheDocument();
    expect(screen.getByText(/Possible events from email/i)).toBeInTheDocument();
    expect(screen.getByText(/can't confirm/i)).toBeInTheDocument();
  });
});

describe("Hero section", () => {
  it("shows an empty state when there is no strong candidate", () => {
    const hero: HeroState = {
      present: false, kind: "none", title: "", people: [], related_emails: [],
      prep_checklist: [], badges: [], evidence: [],
    };
    render(<Hero meta={{ ...meta, id: "hero" }} hero={hero} />);
    expect(screen.getByText(/clear/i)).toBeInTheDocument();
  });
});

describe("Approvals section", () => {
  it("calls the gated backend on approve", async () => {
    const onDecision = vi.fn().mockResolvedValue(undefined);
    const items: ApprovalSummary[] = [{
      id: 7, action_type: "delete", summary: "Delete DSI events", confidence: 0.9,
      item_count: 3, required_phrase: "CONFIRM DELETE", evidence: [],
    }];
    render(
      <MemoryRouter>
        <Approvals meta={{ ...meta, id: "approvals" }} items={items} onDecision={onDecision} />
      </MemoryRouter>,
    );
    expect(screen.getByText("CONFIRM DELETE")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Approve"));
    expect(onDecision).toHaveBeenCalledWith(7, "confirm");
  });
});
