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
  ArrowLeftRight,
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

const gameOptions = [
  { value: "all", label: "ALL" },
  { value: "cs2", label: "CS2" },
  { value: "rust", label: "RUST" },
  { value: "tf2", label: "TF2" },
];

const serviceOptions = [
  { value: "marketcsgo", label: "MarketCSGO" },
  { value: "dmarket", label: "DMarket" },
  { value: "lootfarm", label: "LootFarm" },
];

const columns = [
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
  { id: "name", label: "Name", type: "text" },
  { id: "best_sell", label: "Price", type: "number" },
  { id: "potential_profit_abs", label: "Profit", type: "number" },
  { id: "potential_profit_percent", label: "Profit %", type: "number" },
  { id: "liquidity", label: "Liquidity", type: "number" },
];

const arbitrageFilterColumns = [
  { id: "name", label: "Name", type: "text" },
  { id: "buy_price", label: "Buy Price", type: "number" },
  { id: "sell_price", label: "Sell Price", type: "number" },
  { id: "net_sell_price", label: "Net Sell", type: "number" },
  { id: "profit", label: "Profit", type: "number" },
  { id: "profit_percent", label: "Profit %", type: "number" },
];

function createEmptyFilters(columnsForFilters = filterColumns) {
  return Object.fromEntries(
    columnsForFilters.map((column) => [
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

function formatUsd(value) {
  if (value === null || value === undefined) {
    return "-";
  }

  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(Number(value));
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

function normalizeFilterValue(value, type) {
  if (value === "") {
    return null;
  }

  if (type === "number") {
    return Number(value);
  }

  return value;
}

function buildApiFilters(filters, columnsForFilters = filterColumns) {
  return columnsForFilters.reduce((result, column) => {
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
  const [activeTab, setActiveTab] = useState("orders");
  const [items, setItems] = useState([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(100);
  const [sort, setSort] = useState(null);
  const [arbitrageSettings, setArbitrageSettings] = useState({
    game: "cs2",
    firstService: "marketcsgo",
    secondService: "marketcsgo",
    autoUpdate: false,
    firstNormal: true,
    firstOrders: false,
    secondNormal: false,
    secondOrders: true,
    lootfarmNoOverstock: true,
  });
  const [arbitrageItems, setArbitrageItems] = useState([]);
  const [arbitragePage, setArbitragePage] = useState(1);
  const [arbitragePageSize, setArbitragePageSize] = useState(50);
  const [arbitrageSort, setArbitrageSort] = useState({ field: "profit", orderType: "desc" });
  const [arbitrageTotalFound, setArbitrageTotalFound] = useState(0);
  const [arbitrageMeta, setArbitrageMeta] = useState(null);
  const [arbitrageLoading, setArbitrageLoading] = useState(false);
  const [arbitrageError, setArbitrageError] = useState("");
  const [draftFilters, setDraftFilters] = useState(createEmptyFilters);
  const [appliedFilters, setAppliedFilters] = useState(createEmptyFilters);
  const [draftArbitrageFilters, setDraftArbitrageFilters] = useState(() => createEmptyFilters(arbitrageFilterColumns));
  const [appliedArbitrageFilters, setAppliedArbitrageFilters] = useState(() => createEmptyFilters(arbitrageFilterColumns));
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
  const appliedArbitrageFilterCount = useMemo(
    () => Object.keys(buildApiFilters(appliedArbitrageFilters, arbitrageFilterColumns)).length,
    [appliedArbitrageFilters],
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

  async function loadArbitrage(signal) {
    const firstPriceTypes = getArbitragePriceTypes(arbitrageSettings, "first");
    const secondPriceTypes = getArbitragePriceTypes(arbitrageSettings, "second");

    setArbitrageLoading(true);
    setArbitrageError("");

    try {
      const response = await fetch(`${API_URL}/arbitrage/search`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          game: arbitrageSettings.game,
          first_service: arbitrageSettings.firstService,
          second_service: arbitrageSettings.secondService,
          first_price_types: firstPriceTypes,
          second_price_types: secondPriceTypes,
          lootfarm_no_overstock: arbitrageSettings.lootfarmNoOverstock,
          sort: {
            field: arbitrageSort.field,
            order_type: arbitrageSort.orderType,
          },
          filters: buildApiFilters(appliedArbitrageFilters, arbitrageFilterColumns),
          page: arbitragePage,
        }),
        signal,
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail ?? `API returned ${response.status}`);
      }

      const data = await response.json();
      setArbitrageItems(data.items ?? []);
      setArbitragePageSize(data.page_size ?? 50);
      setArbitrageTotalFound(data.total_found ?? 0);
      setArbitrageMeta({
        sourceItems: data.source_items ?? 0,
        priceMatches: data.price_matches ?? {},
      });
    } catch (requestError) {
      if (requestError.name !== "AbortError") {
        setArbitrageError(requestError.message);
      }
    } finally {
      setArbitrageLoading(false);
    }
  }

  useEffect(() => {
    if (activeTab !== "orders") {
      return undefined;
    }

    const controller = new AbortController();
    loadSkins(controller.signal);

    return () => controller.abort();
  }, [activeTab, page, sort?.field, sort?.orderType, appliedFilters]);

  useEffect(() => {
    if (activeTab !== "arbitrage") {
      return undefined;
    }

    const controller = new AbortController();
    loadArbitrage(controller.signal);

    return () => controller.abort();
  }, [
    activeTab,
    arbitragePage,
    arbitrageSettings.game,
    arbitrageSettings.firstService,
    arbitrageSettings.secondService,
    arbitrageSettings.firstNormal,
    arbitrageSettings.firstOrders,
    arbitrageSettings.secondNormal,
    arbitrageSettings.secondOrders,
    arbitrageSettings.lootfarmNoOverstock,
    arbitrageSort.field,
    arbitrageSort.orderType,
    appliedArbitrageFilters,
  ]);

  useEffect(() => {
    if (activeTab !== "arbitrage" || !arbitrageSettings.autoUpdate) {
      return undefined;
    }

    const intervalId = window.setInterval(() => loadArbitrage(), 30000);
    return () => window.clearInterval(intervalId);
  }, [activeTab, arbitrageSettings.autoUpdate, arbitrageSettings, appliedArbitrageFilters]);

  function updateSort(field) {
    setSort((currentSort) => getNextSort(currentSort, field));
    setPage(1);
  }

  function updateArbitrageSort(field) {
    setArbitrageSort((currentSort) => getNextSort(currentSort, field) ?? { field, orderType: "desc" });
    setArbitragePage(1);
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

  function updateArbitrageSetting(field, value) {
    setArbitrageSettings((currentSettings) => ({
      ...currentSettings,
      [field]: value,
    }));
    setArbitragePage(1);
  }

  function switchArbitrageServices() {
    setArbitrageSettings((currentSettings) => ({
      ...currentSettings,
      firstService: currentSettings.secondService,
      secondService: currentSettings.firstService,
      firstNormal: currentSettings.secondNormal,
      firstOrders: currentSettings.secondOrders,
      secondNormal: currentSettings.firstNormal,
      secondOrders: currentSettings.firstOrders,
    }));
    setArbitragePage(1);
  }

  function updateArbitrageFilter(field, key, value) {
    setDraftArbitrageFilters((currentFilters) => ({
      ...currentFilters,
      [field]: {
        ...currentFilters[field],
        [key]: value,
      },
    }));
  }

  function applyArbitrageFilters(event) {
    event.preventDefault();
    setAppliedArbitrageFilters(draftArbitrageFilters);
    setArbitragePage(1);
  }

  function resetArbitrageFilters() {
    const emptyFilters = createEmptyFilters(arbitrageFilterColumns);
    setDraftArbitrageFilters(emptyFilters);
    setAppliedArbitrageFilters(emptyFilters);
    setArbitragePage(1);
  }

  return (
    <main className="app-shell">
      <section className="top-bar">
        <div>
          <h1>Steam Orders</h1>
          <p>
            {activeTab === "orders"
              ? `${pageSize} skins per page from Postgres${appliedFilterCount > 0 ? `, ${appliedFilterCount} filters active` : ""}`
              : `${arbitrageTotalFound} arbitrage variants found${appliedArbitrageFilterCount > 0 ? `, ${appliedArbitrageFilterCount} filters active` : ""}`}
          </p>
        </div>

        <button
          className="icon-button refresh-button"
          type="button"
          onClick={() => (activeTab === "orders" ? loadSkins() : loadArbitrage())}
          disabled={activeTab === "orders" ? loading : arbitrageLoading}
          title="Refresh"
          aria-label="Refresh"
        >
          <RefreshCcw size={18} />
        </button>
      </section>

      <nav className="tabs" aria-label="Views">
        <button
          className={`tab-button ${activeTab === "orders" ? "active-tab" : ""}`}
          type="button"
          onClick={() => setActiveTab("orders")}
        >
          Orders
        </button>
        <button
          className={`tab-button ${activeTab === "arbitrage" ? "active-tab" : ""}`}
          type="button"
          onClick={() => setActiveTab("arbitrage")}
        >
          Arbitrage
        </button>
      </nav>

      {activeTab === "orders" ? (
        <>
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
        </>
      ) : (
        <section className="arbitrage-panel">
          <div className="arbitrage-header">
            <h2>Arbitrage</h2>
            <label className="toggle-control">
              <input
                type="checkbox"
                checked={arbitrageSettings.autoUpdate}
                onChange={(event) => updateArbitrageSetting("autoUpdate", event.target.checked)}
              />
              <span>Auto Update</span>
              <strong>{arbitrageSettings.autoUpdate ? "ON" : "OFF"}</strong>
            </label>
          </div>

          <div className="arbitrage-filters">
            <label className="select-control">
              <span>Games</span>
              <select
                value={arbitrageSettings.game}
                onChange={(event) => updateArbitrageSetting("game", event.target.value)}
              >
                {gameOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="select-control">
              <span>First Service</span>
              <select
                value={arbitrageSettings.firstService}
                onChange={(event) => updateArbitrageSetting("firstService", event.target.value)}
              >
                {serviceOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <fieldset className="mode-group">
              <legend>First Price Types</legend>
              {arbitrageSettings.firstService === "lootfarm" ? (
                <span className="fixed-mode">Buy from bot</span>
              ) : (
                <>
                  <label className="checkbox-control">
                    <input
                      type="checkbox"
                      checked={arbitrageSettings.firstNormal}
                      onChange={(event) => updateArbitrageSetting("firstNormal", event.target.checked)}
                    />
                    Normal
                  </label>
                  <label className="checkbox-control">
                    <input
                      type="checkbox"
                      checked={arbitrageSettings.firstOrders}
                      onChange={(event) => updateArbitrageSetting("firstOrders", event.target.checked)}
                    />
                    Orders
                  </label>
                </>
              )}
            </fieldset>

            <button
              className="switch-button"
              type="button"
              onClick={switchArbitrageServices}
              title="Switch services"
              aria-label="Switch services"
            >
              <ArrowLeftRight size={18} />
              Switch
            </button>

            <label className="select-control">
              <span>Second Service</span>
              <select
                value={arbitrageSettings.secondService}
                onChange={(event) => updateArbitrageSetting("secondService", event.target.value)}
              >
                {serviceOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <fieldset className="mode-group">
              <legend>Second Price Types</legend>
              {arbitrageSettings.secondService === "lootfarm" ? (
                <span className="fixed-mode">Sell to bot</span>
              ) : (
                <>
                  <label className="checkbox-control">
                    <input
                      type="checkbox"
                      checked={arbitrageSettings.secondNormal}
                      onChange={(event) => updateArbitrageSetting("secondNormal", event.target.checked)}
                    />
                    Normal
                  </label>
                  <label className="checkbox-control">
                    <input
                      type="checkbox"
                      checked={arbitrageSettings.secondOrders}
                      onChange={(event) => updateArbitrageSetting("secondOrders", event.target.checked)}
                    />
                    Orders
                  </label>
                </>
              )}
            </fieldset>

            {(arbitrageSettings.firstService === "lootfarm" || arbitrageSettings.secondService === "lootfarm") ? (
              <label className="toggle-control lootfarm-overstock-filter">
                <input
                  type="checkbox"
                  checked={arbitrageSettings.lootfarmNoOverstock}
                  onChange={(event) => updateArbitrageSetting("lootfarmNoOverstock", event.target.checked)}
                />
                <span>Без оверстока</span>
              </label>
            ) : null}
          </div>

          <form className="filters-panel arbitrage-filter-panel" onSubmit={applyArbitrageFilters}>
            <div className="filters-header">
              <div className="filters-title">
                <Filter size={17} />
                Filters
              </div>

              <div className="filters-actions">
                <button
                  className="secondary-button"
                  type="button"
                  onClick={resetArbitrageFilters}
                  disabled={arbitrageLoading}
                >
                  <RotateCcw size={16} />
                  Reset
                </button>
                <button className="primary-button" type="submit" disabled={arbitrageLoading}>
                  Apply
                </button>
              </div>
            </div>

            <div className="filters-grid">
              {arbitrageFilterColumns.map((column) => {
                const filterValue = draftArbitrageFilters[column.id];

                return (
                  <div className="filter-row" key={column.id}>
                    <label className="filter-label" htmlFor={`arbitrage-${column.id}-min`}>
                      {column.label}
                    </label>

                    {column.type === "text" ? (
                      <input
                        id={`arbitrage-${column.id}-contains`}
                        type="text"
                        value={filterValue.contains}
                        onChange={(event) => updateArbitrageFilter(column.id, "contains", event.target.value)}
                        placeholder="Contains"
                      />
                    ) : (
                      <div className="range-inputs">
                        <input
                          id={`arbitrage-${column.id}-min`}
                          type={column.type}
                          value={filterValue.min}
                          onChange={(event) => updateArbitrageFilter(column.id, "min", event.target.value)}
                          placeholder="Min"
                        />
                        <input
                          id={`arbitrage-${column.id}-max`}
                          type={column.type}
                          value={filterValue.max}
                          onChange={(event) => updateArbitrageFilter(column.id, "max", event.target.value)}
                          placeholder="Max"
                        />
                      </div>
                    )}

                    <label className="not-null-control">
                      <input
                        type="checkbox"
                        checked={filterValue.notNull}
                        onChange={(event) => updateArbitrageFilter(column.id, "notNull", event.target.checked)}
                      />
                      Not null
                    </label>
                  </div>
                );
              })}
            </div>
          </form>

          {arbitrageError ? (
            <div className="status status-error">
              Failed to load arbitrage: {arbitrageError}
            </div>
          ) : null}

          {arbitrageMeta ? (
            <div className="status status-muted">
              Source skins: {arbitrageMeta.sourceItems}; price matches:{" "}
              {Object.entries(arbitrageMeta.priceMatches)
                .map(([service, matches]) => `${service} ${Object.entries(matches)
                  .map(([type, count]) => `${type}=${count}`)
                  .join("/")}`)
                .join(", ")}
            </div>
          ) : null}

          <section className="table-wrap arbitrage-table-wrap" aria-busy={arbitrageLoading}>
            <table>
              <thead>
                <tr>
                  <th>Item</th>
                  <th className="align-right">Buy Price</th>
                  <th>Buy Link</th>
                  <th className="align-right">Sell Price</th>
                  <th>Sell Link</th>
                  <th className="align-right">Stock</th>
                  <th className="align-right">Net Sell</th>
                  <th className="align-right">
                    <button
                      className={`header-button ${arbitrageSort.field === "profit" ? "active-sort" : ""}`}
                      type="button"
                      onClick={() => updateArbitrageSort("profit")}
                    >
                      <span>Profit</span>
                      <SortIcon active={arbitrageSort.field === "profit"} orderType={arbitrageSort.orderType} />
                    </button>
                  </th>
                  <th className="align-right">
                    <button
                      className={`header-button ${arbitrageSort.field === "profit_percent" ? "active-sort" : ""}`}
                      type="button"
                      onClick={() => updateArbitrageSort("profit_percent")}
                    >
                      <span>Profit %</span>
                      <SortIcon active={arbitrageSort.field === "profit_percent"} orderType={arbitrageSort.orderType} />
                    </button>
                  </th>
                </tr>
              </thead>
              <tbody>
                {arbitrageItems.map((item) => {
                  const lootfarmLimitPrice = isLootfarmLimitPrice(item);

                  return (
                    <tr key={`${item.name}-${item.buy_service}-${item.buy_type}-${item.sell_service}-${item.sell_type}`}>
                      <td className={`name-cell ${lootfarmLimitPrice ? "lootfarm-limit-item" : ""}`}>
                        {item.name}
                      </td>
                      <td className="align-right">{formatUsd(item.buy_price)}</td>
                      <td><MarketplaceLink href={item.buy_url} /></td>
                      <td className="align-right">{formatUsd(item.sell_price)}</td>
                      <td><MarketplaceLink href={item.sell_url} /></td>
                      <td className="align-right">{formatLootfarmStock(item)}</td>
                      <td className="align-right">{formatUsd(item.net_sell_price)}</td>
                      <td className="align-right">
                        <ProfitValue value={item.profit} suffix=" USD" />
                      </td>
                      <td className="align-right">
                        <ProfitValue value={item.profit_percent} suffix="%" />
                      </td>
                    </tr>
                  );
                })}

                {!arbitrageLoading && arbitrageItems.length === 0 ? (
                  <tr>
                    <td className="empty-state" colSpan={9}>
                      No arbitrage variants found
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>

            {arbitrageLoading ? (
              <div className="loading-overlay">Loading</div>
            ) : null}
          </section>

          <section className="pagination">
            <button
              className="page-button"
              type="button"
              onClick={() => setArbitragePage((currentPage) => Math.max(1, currentPage - 1))}
              disabled={arbitragePage === 1 || arbitrageLoading}
            >
              <ArrowLeft size={17} />
              Prev
            </button>

            <span className="page-indicator">Page {arbitragePage}</span>

            <button
              className="page-button"
              type="button"
              onClick={() => setArbitragePage((currentPage) => currentPage + 1)}
              disabled={arbitrageItems.length < arbitragePageSize || arbitrageLoading}
            >
              Next
              <ArrowRight size={17} />
            </button>
          </section>
        </section>
      )}
    </main>
  );
}

function MarketplaceLink({ href }) {
  if (!href) {
    return "-";
  }

  return (
    <a
      className="market-link"
      href={href}
      target="_blank"
      rel="noreferrer"
    >
      Open
    </a>
  );
}

function isLootfarmLimitPrice(item) {
  return item.buy_overstock || item.sell_overstock;
}

function formatLootfarmStock(item) {
  if (item.lootfarm_stock_remaining === null || item.lootfarm_stock_remaining === undefined) {
    return "-";
  }

  if (item.lootfarm_stock_limit === null || item.lootfarm_stock_limit === undefined) {
    return String(item.lootfarm_stock_remaining);
  }

  return `${item.lootfarm_stock_remaining}/${item.lootfarm_stock_limit}`;
}

function getArbitragePriceTypes(settings, side) {
  const service = side === "first" ? settings.firstService : settings.secondService;
  if (service === "lootfarm") {
    return side === "first" ? ["normal"] : ["orders"];
  }

  return [
    settings[`${side}Normal`] ? "normal" : null,
    settings[`${side}Orders`] ? "orders" : null,
  ].filter(Boolean);
}

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
