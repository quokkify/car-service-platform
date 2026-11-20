import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AcceptInvitePage } from "./AcceptInvitePage";

const mockApi = vi.hoisted(() => ({
  post: vi.fn(),
  interceptors: {
    response: { use: vi.fn() },
    request: { use: vi.fn() },
  },
}));

vi.mock("../api/client", () => ({ default: mockApi }));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function submitPassword(value: string) {
  render(
    <MemoryRouter initialEntries={["/invite/accept?token=token-123"]}>
      <Routes>
        <Route path="/invite/accept" element={<AcceptInvitePage />} />
      </Routes>
    </MemoryRouter>
  );
  fireEvent.change(screen.getByPlaceholderText("At least 8 characters"), { target: { value } });
  fireEvent.change(screen.getByPlaceholderText("Repeat your password"), { target: { value } });
  fireEvent.click(screen.getByRole("button", { name: "Set Password" }));
}

describe("AcceptInvitePage", () => {
  // Regression guard: the backend now rejects weak passwords with field errors; show them instead of
  // the generic "invalid link" message so the invitee can pick a stronger password.
  it("shows password validation messages from the API", async () => {
    mockApi.post.mockRejectedValue({
      response: { status: 400, data: { password: ["This password is too common."] } },
    });

    submitPassword("password");

    expect(await screen.findByText("This password is too common.")).toBeInTheDocument();
    expect(screen.queryByText("Invalid or expired invite link.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Set Password" })).toBeInTheDocument();
  });

  it("falls back to the API detail for token errors", async () => {
    mockApi.post.mockRejectedValue({
      response: { status: 400, data: { detail: "This invite link has expired" } },
    });

    submitPassword("Str0ng-unique-passphrase");

    expect(await screen.findByText("This invite link has expired")).toBeInTheDocument();
  });
});
