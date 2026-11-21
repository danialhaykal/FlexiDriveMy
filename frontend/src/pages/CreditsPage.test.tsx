import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { CreditsPage } from "./CreditsPage";
import { PhotoCreditLine } from "../components/catalog/PhotoCreditLine";
import { fetchEntireCatalog } from "../api/catalog";
import type { Vehicle } from "../types/catalog";

// FX-2 (item 8): photo credits from the catalog data, through the same helper as the vehicle page - nothing per car.
vi.mock("../api/catalog", () => ({ fetchEntireCatalog: vi.fn() }));
const mockedFetchEntireCatalog = vi.mocked(fetchEntireCatalog);

const BMW_URL = "https://upload.wikimedia.org/wikipedia/commons/thumb/2/2f/BMW_G20.jpg/1280px-BMW_G20.jpg";
const MACAN_URL = "https://thumb.wikimedia.org/wikipedia/commons/thumb/7/7d/Porsche_Macan.jpg/1280px-Porsche_Macan.jpg";

function car(id: number, brand: string, name: string, thumbnail: string): Vehicle {
  return { id, brand: id, brand_name: brand, name, trim: "T", thumbnail_url: thumbnail } as Vehicle;
}

describe("CreditsPage", () => {
  beforeEach(() => {
    mockedFetchEntireCatalog.mockReset();
  });

  it("lists each active car with a Commons photo and its file-page link, and skips the others", async () => {
    mockedFetchEntireCatalog.mockResolvedValueOnce([
      car(5, "BMW", "3 Series", BMW_URL),
      car(7, "Lexus", "ES 250", ""),
      car(16, "Porsche", "Macan Electric", MACAN_URL),
    ]);

    render(<MemoryRouter><CreditsPage /></MemoryRouter>);

    expect(await screen.findByText("BMW 3 Series T")).toBeInTheDocument();
    expect(screen.getByText("Porsche Macan Electric T")).toBeInTheDocument();
    expect(screen.queryByText(/Lexus/)).not.toBeInTheDocument();
    const links = screen.getAllByRole("link", { name: "Wikimedia Commons file page" }).map((a) => a.getAttribute("href"));
    expect(links).toEqual([
      "https://commons.wikimedia.org/wiki/File:BMW_G20.jpg",
      "https://commons.wikimedia.org/wiki/File:Porsche_Macan.jpg",
    ]);
  });

  it("says so and offers Try again when the catalog can't load", async () => {
    mockedFetchEntireCatalog.mockRejectedValueOnce(new Error("down")).mockResolvedValueOnce([car(5, "BMW", "3 Series", BMW_URL)]);
    const user = userEvent.setup();

    render(<MemoryRouter><CreditsPage /></MemoryRouter>);

    expect(await screen.findByText("Could not load the photo credits")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("BMW 3 Series T")).toBeInTheDocument();
  });
});

describe("PhotoCreditLine", () => {
  it("points to the credits page when a listed car has a Commons photo", () => {
    render(<MemoryRouter><PhotoCreditLine thumbnailUrls={["", BMW_URL]} /></MemoryRouter>);

    expect(screen.getByText(/Photos: Wikimedia Commons/)).toHaveTextContent("Photos: Wikimedia Commons (see credits)");
    expect(screen.getByRole("link", { name: "see credits" })).toHaveAttribute("href", "/credits");
  });

  it("is absent when no listed car has one", () => {
    const { container } = render(<MemoryRouter><PhotoCreditLine thumbnailUrls={["", null, "https://example.com/x.jpg"]} /></MemoryRouter>);

    expect(container).toBeEmptyDOMElement();
  });
});
