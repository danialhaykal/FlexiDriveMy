import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { PageHeader } from "./PageHeader";
import { Button } from "./Button";

describe("PageHeader", () => {
  it("renders the title as the page's h1 with its subtitle", () => {
    render(<PageHeader title="Your financing options" subtitle="BMW 3 Series 320i Sport" />);

    expect(screen.getByRole("heading", { level: 1, name: "Your financing options" })).toBeInTheDocument();
    expect(screen.getByText("BMW 3 Series 320i Sport")).toBeInTheDocument();
  });

  it("renders the breadcrumb and the actions", () => {
    render(
      <PageHeader
        title="Compare"
        breadcrumb={<a href="/catalog">Browse Catalog</a>}
        actions={<Button variant="secondary">Save</Button>}
      />,
    );

    expect(screen.getByRole("link", { name: "Browse Catalog" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
  });

  it("leaves out the optional parts when they are not given", () => {
    const { container } = render(<PageHeader title="Only a title" />);

    expect(container.querySelectorAll("p")).toHaveLength(0);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
