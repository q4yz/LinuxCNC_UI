// Temperature Pinia store. Owns the sensor / heater set, the
// rolling 30 s chart history, the unit toggle, and the per-entry
// visibility / colour maps.

import { defineStore, storeToRefs } from "pinia";
import { computed, onScopeDispose, ref, watch, type Ref } from "vue";

import { temperatureUnit, sensorColors as sensorColorsSetting } from "../settings/definitions/temperature";
import { useBaseThreadStore } from "./baseThread";
import { TemperatureUnit } from "../entities";
import { HeaterReading, type ReadingSet } from "../entities/temperature";

import type { CommandResult } from "../entities";
import {HeaterControlRequest} from "../entities/tools/Heater";
import TemperatureService from "../facades/temperatureFacade";

const TEMPERATURE_ID = "temperature";

// Chart is locked to a fixed 30 s window of 1 s ticks.
const WINDOW_SECONDS = 30;
const DEFAULT_POLL_MS = 1_000;

// Purple fallback color
const FALLBACK_COLOR = "#A855F7";
const DEFAULT_SENSOR_COLORS: Record<string, string> = {};

const STORE_ID = TEMPERATURE_ID;

// Singleton settings client

function clone<T>(value: T): T {
    if (typeof structuredClone === "function") {
        try {
            return structuredClone(value);
        } catch (_) {
            // Fall through to JSON path.
        }
    }
    return JSON.parse(JSON.stringify(value));
}

function roundTo(value: number, decimals: number): number {
    if (!Number.isFinite(value)) return 0;
    const factor = Math.pow(10, decimals);
    return Math.round(value * factor) / factor;
}

interface ChartSensorShape {
    actual: number;
    target?: number;
}

interface HistoryPoint {
    timestamp: number;
    time: string;
    sensors: Record<string, ChartSensorShape>;
}

function readingsToChartShape(readings: ReadingSet): Record<string, ChartSensorShape> {
    const out: Record<string, ChartSensorShape> = {};
    readings.forEach((r) => {
        out[r.id] = {
            actual: r.actualCelsius,
            ...(r instanceof HeaterReading && r.isControllable && { target: r.targetCelsius }),
        };
    });
    return out;
}

export const useTemperatureStore = defineStore(
    STORE_ID,
    () => {
        // --- reactive state ------------------------------------------- //
        const sensors: Ref<Record<string, ChartSensorShape>> = ref({});
        const history: Ref<HistoryPoint[]> = ref([]);
        const windowMs = ref(WINDOW_SECONDS * 1000);
        const pollMs = ref(DEFAULT_POLL_MS);
        // Display unit + colours are central UI settings
        // (``settings/definitions/temperature``); their defaults apply
        // until the stored values arrive.
        const unit = computed<TemperatureUnit>(() => temperatureUnit.value ?? TemperatureUnit.CELSIUS);
        const visibleSensors: Ref<Record<string, boolean>> = ref({});
        const sensorColors = computed<Record<string, string>>(() => ({
            ...DEFAULT_SENSOR_COLORS,
            ...(sensorColorsSetting.value ?? {}),
        }));

        // --- non-reactive handles ------------------------------------- //
        let pollHandle: ReturnType<typeof setInterval> | null = null;
        let running = false;

        // --- helpers -------------------------------------------------- //

        function seedVisibility(readings: ReadingSet) {
            const next: Record<string, boolean> = {};
            readings.forEach((r) => {
                if (typeof visibleSensors.value[r.id] === "boolean") {
                    next[r.id] = visibleSensors.value[r.id];
                } else {
                    next[r.id] = true;
                }
            });
            visibleSensors.value = next;
        }

        function displayTemp(celsius: number | null | undefined): number {
            if (!Number.isFinite(celsius)) return 0;
            const val = celsius as number;
            const value = unit.value === TemperatureUnit.KELVIN ? val + 273.15 : val;
            return roundTo(value, 2);
        }

        /** Persist the display unit (the setting reports failures itself). */
        async function setUnit(nextUnit: TemperatureUnit): Promise<boolean> {
            return (await temperatureUnit.save(nextUnit)).ok;
        }

        function toggleSensorVisibility(name: string) {
            const current = visibleSensors.value[name];
            visibleSensors.value = {
                ...visibleSensors.value,
                [name]: !(current !== false),
            };
        }

        async function setSensorColor(name: string, hex: string) {
            await sensorColorsSetting.setColor(name, hex);
        }

        function colorFor(name: string): string {
            return sensorColors.value[name] || FALLBACK_COLOR;
        }

        function snapshot() {
            const now = Date.now();
            const date = new Date(now);
            const pad = (n: number) => n.toString().padStart(2, "0");
            const cents = Math.floor(date.getMilliseconds() / 10);
            const label = `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(
                date.getSeconds(),
            )}.${cents.toString().padStart(2, "0")}`;

            history.value.push({
                timestamp: now,
                time: label,
                sensors: clone(sensors.value || {}),
            });
            const cutoff = now - windowMs.value;
            history.value = history.value.filter((p) => p.timestamp >= cutoff);
        }

        function start() {
            if (running) return;
            running = true;
            snapshot();
            pollHandle = setInterval(snapshot, pollMs.value);
        }

        function stop() {
            running = false;
            if (pollHandle !== null) {
                clearInterval(pollHandle);
                pollHandle = null;
            }
        }

        function ingest(readings: ReadingSet) {
            if (!readings || typeof readings.forEach !== "function") return;
            sensors.value = readingsToChartShape(readings);
            seedVisibility(readings);
        }

        /**
         * Set the target temperature for a heater using the HeaterControlRequest DTO.
         */
        async function setTarget(request: HeaterControlRequest): Promise<CommandResult> {
            return await TemperatureService.setTarget(request);
        }

        async function refreshSensors() {
            await useBaseThreadStore().refresh();
        }

        // --- base-thread consumer -------------------------------------- //
        const baseThread = useBaseThreadStore();
        ingest(baseThread.readings);

        const stopReadingsWatch = watch(
            () => baseThread.readings,
            (next) => {
                if (next && typeof next.forEach === "function") {
                    ingest(next);
                }
            },
            { immediate: true, deep: true },
        );


        onScopeDispose(() => {
            stop();
            if (stopReadingsWatch) {
                stopReadingsWatch();
            }
        });

        return {
            sensors,
            history,
            windowMs,
            pollMs,
            unit,
            visibleSensors,
            sensorColors,
            ingest,
            snapshot,
            start,
            stop,
            refreshSensors,
            displayTemp,
            setUnit,
            toggleSensorVisibility,
            setSensorColor,
            colorFor,
            setTarget,
        };
    },
);

export function useTemperatureRefs() {
    const store = useTemperatureStore();
    return { store, ...storeToRefs(store) };
}

export default useTemperatureStore;