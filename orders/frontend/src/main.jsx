import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  ChevronsUpDown,
  Filter,
  RefreshCcw,
  RotateCcw,
} from "lucide-react";
import "./styles.css";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

const DEFAULT_SORT = {
  field: "last_update",
  orderType: "desc",
};

const columns = [
  {
    accessorKey: "id",
    header: "ID",
    meta: { align: "right" },
  },
  {
    accessorKey: "name",
    header: "Name",
    cell: ({ getValue }) => <MarketLink name={getValue()} />,
    meta: { className: "name-cell" },
  },
  {
    accessorKey: "best_sell",
    header: "Best Sell",
    cell: ({ getValue }) => formatMoney(getValue()),
    meta: { align: "right" },
  },
  {
    accessorKey: "best_buy",
    header: "Best Buy",
    cell: ({ getValue }) => formatMoney(getValue()),
    meta: { align: "right" },
  },
  {
    accessorKey: "potential_profit_abs",
    header: "Profit",
    cell: ({ getValue }) => (
      <ProfitValue value={getValue()} suffix=" RUB" />
    ),
    meta: { align: "right" },
  },
  {
    accessorKey: "potential_profit_percent",
    header: "Profit %",
    cell: ({ getValue }) => (
      <ProfitValue value={getValue()} suffix="%" />
    ),
    meta: { align: "right" },
  },
  {
    accessorKey: "liquidity",
    header: "Liquidity",
    cell: ({ getValue }) => formatNumber(getValue()),
    meta: { align: "right" },
  },
  {
    accessorKey: "last_update",
    header: "Last Update",
    cell: ({ getValue }) => formatDate(getValue()),
  },
];

const filterColumns = [
  { id: "id", label: "ID", type: "number" },
  { id: "name", label: "Name", type: "text" },
  { id: "best_sell", label: "Best Sell", type: "number" },
  { id: "best_buy", label: "Best Buy", type: "number" },
  { id: "potential_profit_abs", label: "Profit", type: "number" },
  { id: "potential_profit_percent", label: "Profit %", type: "number" },
  { id: "liquidity", label: "Liquidity", type: "number" },
  { id: "last_update", label: "Last Update", type: "datetime-local" },
];

function createEmptyFilters() {
  return Object.fromEntries(
    filterColumns.map((column) => [
      column.id,
      {
        min: "",
        max: "",
        contains: "",
        notNull: false,
      },
    ]),
  );
}

function formatNumber(value) {
  if (value === null || value === undefined) {
    return "-";
  }

  return new Intl.NumberFormat("ru-RU", {
    maximumFractionDigits: 2,
  }).format(Number(value));
}

function formatMoney(value) {
  if (value === null || value === undefined) {
    return "-";
  }

  return `${formatNumber(value)} RUB`;
}

function formatDate(value) {
  if (!value) {
    return "-";
  }

  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "short",
    timeStyle: "medium",
  }).format(new Date(value));
}

function getMarketUrl(name) {
  return `https://steamcommunity.com/market/listings/730/${encodeURIComponent(name)}`;
}

function toApiDateTime(value) {
  if (!value) {
    return "";
  }

  return new Date(value).toISOString();
}

function normalizeFilterValue(value, type) {
  if (value === "") {
    return null;
  }

  if (type === "datetime-local") {
    return toApiDateTime(value);
  }

  if (type === "number") {
    return Number(value);
  }

  return value;
}

function buildApiFilters(filters) {
  return filterColumns.reduce((result, column) => {
    const filterValue = filters[column.id];
    const apiFilter = {};

    if (column.type === "text") {
      if (filterValue.contains.trim()) {
        apiFilter.contains = filterValue.contains.trim();
      }
    } else {
      const min = normalizeFilterValue(filterValue.min, column.type);
      const max = normalizeFilterValue(filterValue.max, column.type);

      if (min !== null) {
        apiFilter.min = min;
      }

      if (max !== null) {
        apiFilter.max = max;
      }
    }

    if (filterValue.notNull) {
      apiFilter.not_null = true;
    }

    if (Object.keys(apiFilter).length > 0) {
      result[column.id] = apiFilter;
    }

    return result;
  }, {});
}

function MarketLink({ name }) {
  if (!name) {
    return "-";
  }

  return (
    <a
      className="market-link"
      href={getMarketUrl(name)}
      target="_blank"
      rel="noreferrer"
    >
      {name}
    </a>
  );
}

function ProfitValue({ value, suffix }) {
  if (value === null || value === undefined) {
    return "-";
  }

  const numericValue = Number(value);
  const className = numericValue > 0 ? "profit-positive" : numericValue < 0 ? "profit-negative" : "";

  return (
    <span className={className}>
      {formatNumber(numericValue)}
      {suffix}
    </span>
  );
}

function getNextSort(currentSort, field) {
  if (!currentSort) {
    return {
      field,
      orderType: "asc",
    };
  }

  if (currentSort.field !== field) {
    return {
      field,
      orderType: "asc",
    };
  }

  if (currentSort.orderType === "asc") {
    return {
      field,
      orderType: "desc",
    };
  }

  return null;
}

function SortIcon({ active, orderType }) {
  if (!active) {
    return <ChevronsUpDown size={15} aria-hidden="true" />;
  }

  return orderType === "asc"
    ? <ArrowUp size={15} aria-hidden="true" />
    : <ArrowDown size={15} aria-hidden="true" />;
}

function App() {
  const [items, setItems] = useState([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(100);
  const [sort, setSort] = useState(null);
  const [draftFilters, setDraftFilters] = useState(createEmptyFilters);
  const [appliedFilters, setAppliedFilters] = useState(createEmptyFilters);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const table = useReactTable({
    data: items,
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true,
  });

  const hasNextPage = useMemo(
    () => items.length === pageSize && items.length > 0,
    [items.length, pageSize],
  );
  const appliedFilterCount = useMemo(
    () => Object.keys(buildApiFilters(appliedFilters)).length,
    [appliedFilters],
  );

  async function loadSkins(signal) {
    const payload = {
      page,
      sort: {
        field: sort?.field ?? DEFAULT_SORT.field,
        order_type: sort?.orderType ?? DEFAULT_SORT.orderType,
      },
      filters: buildApiFilters(appliedFilters),
    };

    setLoading(true);
    setError("");

    try {
      const response = await fetch(`${API_URL}/skins/search`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
        signal,
      });

      if (!response.ok) {
        throw new Error(`API returned ${response.status}`);
      }

      const data = await response.json();
      setItems(data.items ?? []);
      setPageSize(data.page_size ?? 100);
    } catch (requestError) {
      if (requestError.name !== "AbortError") {
        setError(requestError.message);
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    loadSkins(controller.signal);

    return () => controller.abort();
  }, [page, sort?.field, sort?.orderType, appliedFilters]);

  function updateSort(field) {
    setSort((currentSort) => getNextSort(currentSort, field));
    setPage(1);
  }

  function updateFilter(field, key, value) {
    setDraftFilters((currentFilters) => ({
      ...currentFilters,
      [field]: {
        ...currentFilters[field],
        [key]: value,
      },
    }));
  }

  function applyFilters(event) {
    event.preventDefault();
    setAppliedFilters(draftFilters);
    setPage(1);
  }

  function resetFilters() {
    const emptyFilters = createEmptyFilters();
    setDraftFilters(emptyFilters);
    setAppliedFilters(emptyFilters);
    setPage(1);
  }

  return (
    <main className="app-shell">
      <section className="top-bar">
        <div>
          <h1>Steam Orders</h1>
          <p>
            {pageSize} skins per page from Postgres
            {appliedFilterCount > 0 ? `, ${appliedFilterCount} filters active` : ""}
          </p>
        </div>

        <button
          className="icon-button refresh-button"
          type="button"
          onClick={() => loadSkins()}
          disabled={loading}
          title="Refresh"
          aria-label="Refresh"
        >
          <RefreshCcw size={18} />
        </button>
      </section>

      <form className="filters-panel" onSubmit={applyFilters}>
        <div className="filters-header">
          <div className="filters-title">
            <Filter size={17} />
            Filters
          </div>

          <div className="filters-actions">
            <button
              className="secondary-button"
              type="button"
              onClick={resetFilters}
              disabled={loading}
            >
              <RotateCcw size={16} />
              Reset
            </button>
            <button className="primary-button" type="submit" disabled={loading}>
              Apply
            </button>
          </div>
        </div>

        <div className="filters-grid">
          {filterColumns.map((column) => {
            const filterValue = draftFilters[column.id];

            return (
              <div className="filter-row" key={column.id}>
                <label className="filter-label" htmlFor={`${column.id}-min`}>
                  {column.label}
                </label>

                {column.type === "text" ? (
                  <input
                    id={`${column.id}-contains`}
                    type="text"
                    value={filterValue.contains}
                    onChange={(event) => updateFilter(column.id, "contains", event.target.value)}
                    placeholder="Contains"
                  />
                ) : (
                  <div className="range-inputs">
                    <input
                      id={`${column.id}-min`}
                      type={column.type}
                      value={filterValue.min}
                      onChange={(event) => updateFilter(column.id, "min", event.target.value)}
                      placeholder="Min"
                    />
                    <input
                      id={`${column.id}-max`}
                      type={column.type}
                      value={filterValue.max}
                      onChange={(event) => updateFilter(column.id, "max", event.target.value)}
                      placeholder="Max"
                    />
                  </div>
                )}

                <label className="not-null-control">
                  <input
                    type="checkbox"
                    checked={filterValue.notNull}
                    onChange={(event) => updateFilter(column.id, "notNull", event.target.checked)}
                  />
                  Not null
                </label>
              </div>
            );
          })}
        </div>
      </form>

      {error ? (
        <div className="status status-error">
          Failed to load skins: {error}
        </div>
      ) : null}

      <section className="table-wrap" aria-busy={loading}>
        <table>
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => {
                  const field = header.column.id;
                  const active = sort?.field === field;

                  return (
                    <th
                      key={header.id}
                      className={header.column.columnDef.meta?.align === "right" ? "align-right" : ""}
                    >
                      <button
                        className={`header-button ${active ? "active-sort" : ""}`}
                        type="button"
                        onClick={() => updateSort(field)}
                      >
                        <span>
                          {flexRender(
                            header.column.columnDef.header,
                            header.getContext(),
                          )}
                        </span>
                        <SortIcon active={active} orderType={sort?.orderType} />
                      </button>
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id}>
                {row.getVisibleCells().map((cell) => (
                  <td
                    key={cell.id}
                    className={[
                      cell.column.columnDef.meta?.align === "right" ? "align-right" : "",
                      cell.column.columnDef.meta?.className ?? "",
                    ].join(" ")}
                  >
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}

            {!loading && items.length === 0 ? (
              <tr>
                <td className="empty-state" colSpan={columns.length}>
                  No skins found
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>

        {loading ? (
          <div className="loading-overlay">Loading</div>
        ) : null}
      </section>

      <section className="pagination">
        <button
          className="page-button"
          type="button"
          onClick={() => setPage((currentPage) => Math.max(1, currentPage - 1))}
          disabled={page === 1 || loading}
        >
          <ArrowLeft size={17} />
          Prev
        </button>

        <span className="page-indicator">Page {page}</span>

        <button
          className="page-button"
          type="button"
          onClick={() => setPage((currentPage) => currentPage + 1)}
          disabled={!hasNextPage || loading}
        >
          Next
          <ArrowRight size={17} />
        </button>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
