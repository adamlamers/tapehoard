<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { RotateCw, Activity, CheckCircle2 } from 'lucide-svelte';
    import { Card } from '$lib/components/ui/card';
    import { getScanStatus } from '$lib/api';
    import { scanStatus } from '$lib/stores/scanStatus';
    import { toast } from 'svelte-sonner';

    let scanEventSource: EventSource | null = null;
    let showCompleted = $state(false);
    let completedTimeout: any;
    let prevIsRunning = false;

    function connectScanSse() {
        if (scanEventSource) return;

        const apiUrl = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8001';
        scanEventSource = new EventSource(`${apiUrl}/system/scan/stream`);

        scanEventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                const wasRunning = prevIsRunning;
                prevIsRunning = data.is_running;
                scanStatus.set(data);

                if (wasRunning && !data.is_running) {
                    toast.success("Filesystem scan completed");
                    showCompleted = true;
                    if (completedTimeout) clearTimeout(completedTimeout);
                    completedTimeout = setTimeout(() => { showCompleted = false; }, 5000);
                }
            } catch (err) {
                console.error('Scan SSE parse error:', err);
            }
        };

        scanEventSource.onerror = () => {
            // EventSource auto-reconnects
        };
    }

    function closeScanSse() {
        if (scanEventSource) {
            scanEventSource.close();
            scanEventSource = null;
        }
    }

    onMount(async () => {
        // Seed the store immediately so other components have an initial value
        try {
            const res = await getScanStatus();
            if (res.data) {
                prevIsRunning = res.data.is_running;
                scanStatus.set(res.data);
            }
        } catch {}
        connectScanSse();
    });

    onDestroy(() => {
        closeScanSse();
        if (completedTimeout) clearTimeout(completedTimeout);
    });
</script>

{#if $scanStatus?.is_running}
    <div class="fixed bottom-6 right-6 z-[100] w-[420px] animate-in fade-in slide-in-from-bottom-4" data-testid="scan-status-overlay">
        <Card class="bg-bg-secondary border-border-color shadow-2xl overflow-hidden">
            <!-- Header -->
            <header class="px-5 py-4 border-b border-border-color bg-bg-tertiary/30 relative overflow-hidden">
                <div class="absolute inset-0 bg-gradient-to-r from-blue-500/5 to-transparent pointer-events-none"></div>
                <div class="flex items-center gap-4 relative z-10">
                    <div class="p-2.5 bg-blue-500/10 rounded-xl text-blue-500 border border-blue-500/20">
                        <RotateCw size={20} class="animate-spin" />
                    </div>
                    <div class="flex-1 min-w-0">
                        <div class="flex items-center justify-between">
                            <h3 class="text-sm font-semibold text-text-primary">Filesystem scan in progress</h3>
                            {#if $scanStatus.is_throttled}
                                <span class="text-[10px] font-medium bg-orange-500/10 text-orange-500 px-2 py-0.5 rounded border border-orange-500/20 ml-2 shrink-0">THROTTLED</span>
                            {/if}
                        </div>
                        <p class="text-xs text-text-secondary mt-0.5">
                            {$scanStatus.files_processed.toLocaleString()} files scanned
                        </p>
                    </div>
                </div>
            </header>

            <!-- Progress -->
            <div class="p-5 space-y-4">
                <div class="w-full bg-bg-primary h-2 rounded-full overflow-hidden">
                    <div
                        class="bg-blue-500 h-full transition-all duration-1000"
                        class:animate-pulse={!$scanStatus.total_files_found}
                        style="width: {$scanStatus.total_files_found
                            ? Math.round(($scanStatus.files_processed / $scanStatus.total_files_found) * 100)
                            : 100}%"
                    ></div>
                </div>

                <div class="grid grid-cols-2 gap-3">
                    <div class="bg-bg-primary/50 rounded-lg px-3 py-2.5 border border-border-color/50">
                        <p class="text-[10px] font-medium text-text-secondary uppercase tracking-wide">New files</p>
                        <p class="text-sm font-semibold mono text-text-primary mt-0.5">{$scanStatus.files_new.toLocaleString()}</p>
                    </div>
                    <div class="bg-bg-primary/50 rounded-lg px-3 py-2.5 border border-border-color/50">
                        <p class="text-[10px] font-medium text-text-secondary uppercase tracking-wide">Modified</p>
                        <p class="text-sm font-semibold mono text-text-primary mt-0.5">{$scanStatus.files_modified.toLocaleString()}</p>
                    </div>
                </div>

                {#if $scanStatus.current_path}
                    <div class="bg-bg-primary/50 rounded-lg px-3 py-2.5 border border-border-color/50">
                        <p class="text-[10px] font-medium text-text-secondary uppercase tracking-wide mb-1">Current file</p>
                        <p class="text-xs text-text-primary mono truncate">{$scanStatus.current_path}</p>
                    </div>
                {/if}

                {#if $scanStatus.hashing_speed}
                    <div class="flex items-center gap-2 text-xs text-text-secondary">
                        <Activity size={12} />
                        <span class="mono">{$scanStatus.hashing_speed}</span>
                    </div>
                {/if}
            </div>
        </Card>
    </div>
{:else if showCompleted && $scanStatus}
    <div class="fixed bottom-6 right-6 z-[100] w-[420px] animate-in fade-in slide-in-from-bottom-4">
        <Card class="bg-bg-secondary border-border-color shadow-2xl overflow-hidden">
            <header class="px-5 py-4 border-b border-border-color bg-bg-tertiary/30 relative overflow-hidden">
                <div class="absolute inset-0 bg-gradient-to-r from-green-500/5 to-transparent pointer-events-none"></div>
                <div class="flex items-center gap-4 relative z-10">
                    <div class="p-2.5 bg-green-500/10 rounded-xl text-green-500 border border-green-500/20">
                        <CheckCircle2 size={20} />
                    </div>
                    <div class="flex-1">
                        <h3 class="text-sm font-semibold text-text-primary">Scan completed</h3>
                        <p class="text-xs text-text-secondary mt-0.5">
                            {$scanStatus.files_processed.toLocaleString()} files indexed
                        </p>
                    </div>
                </div>
            </header>
        </Card>
    </div>
{/if}
