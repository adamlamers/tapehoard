<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { RotateCw, Activity } from 'lucide-svelte';
    import { getScanStatusSystemScanStatusGet, type ScanStatusSchema } from '$lib/api';
    import { toast } from 'svelte-sonner';

    let scanStatus = $state<ScanStatusSchema | null>(null);
    let pollInterval: any;

    async function updateScanStatus() {
        try {
            const response = await getScanStatusSystemScanStatusGet();
            if (response.data) {
                const wasRunning = scanStatus?.is_running;
                scanStatus = response.data;

                if (wasRunning && !scanStatus.is_running) {
                    toast.success("Filesystem scan completed");
                }
            }
        } catch (error) {
            console.error("Failed to get scan status:", error);
        }
    }

    onMount(() => {
        updateScanStatus();
        pollInterval = setInterval(updateScanStatus, 2000);
    });

    onDestroy(() => {
        if (pollInterval) clearInterval(pollInterval);
    });

    const scanProgress = $derived(
        scanStatus?.total_files_found
        ? Math.round((scanStatus.files_processed / scanStatus.total_files_found) * 100)
        : 0
    );
</script>

{#if scanStatus?.is_running}
    <div class="fixed bottom-8 right-8 z-[100] bg-bg-secondary border border-blue-500/30 rounded-xl p-6 shadow-[0_25px_60px_rgba(0,0,0,0.6)] w-[450px] animate-in fade-in slide-in-from-bottom-8 border-l-4 border-l-blue-500 overflow-hidden group">
        <div class="absolute inset-0 bg-gradient-to-br from-blue-500/5 to-transparent pointer-events-none"></div>

        <div class="relative z-10">
            <div class="flex items-center gap-4 mb-6">
                <div class="p-3 bg-blue-500/10 rounded-xl border border-blue-500/20 group-hover:scale-110 transition-transform duration-500">
                    <RotateCw size={24} class="animate-spin text-blue-500" />
                </div>
                <div class="flex-1">
                    <div class="flex justify-between items-center mb-1">
                        <span class="text-xs font-black uppercase tracking-widest text-text-primary">System Scanner Active</span>
                        <div class="flex items-center gap-2">
                            {#if scanStatus.is_throttled}
                                <span class="text-[9px] font-black bg-orange-500/10 text-orange-500 px-2 py-0.5 rounded border border-orange-500/20 animate-pulse">THROTTLED</span>
                            {/if}
                            <span class="text-sm font-black mono text-blue-400">{scanStatus.hashing_speed}</span>
                        </div>
                    </div>
                    <div class="flex items-center gap-2">
                        <div class="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse"></div>
                        <p class="text-[10px] font-bold uppercase tracking-[0.2em] text-text-secondary opacity-60">
                            New: {scanStatus.files_new} &bull; Mod: {scanStatus.files_modified}
                        </p>
                    </div>
                </div>
            </div>

            <div class="space-y-4">
                <div class="flex flex-col gap-3">
                    <div class="flex justify-between items-center text-[10px] font-black uppercase tracking-widest text-text-secondary">
                        <span class="flex items-center gap-2">
                            <Activity size={12} class="opacity-50" />
                            Indexing Fleet
                        </span>
                        <span class="mono text-text-primary">
                            {scanStatus.files_processed.toLocaleString()} / {scanStatus.total_files_found.toLocaleString()}
                        </span>
                    </div>

                    <div class="w-full bg-bg-primary h-1.5 rounded-full border border-white/5 overflow-hidden">
                        <div
                            class="bg-blue-500 h-full transition-all duration-1000 shadow-[0_0_10px_rgba(59,130,246,0.4)]"
                            style="width: {scanProgress}%"
                        ></div>
                    </div>

                    <div class="bg-bg-primary/80 px-4 py-2.5 rounded-lg border border-white/5 shadow-inner">
                        <p class="text-[10px] text-blue-300/80 truncate mono italic leading-relaxed">
                            {scanStatus.current_path || 'Initializing crawler...'}
                        </p>
                    </div>
                </div>
            </div>
        </div>
    </div>
{/if}
