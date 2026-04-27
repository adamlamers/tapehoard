<script lang="ts">
    import { onMount } from 'svelte';
    import {
        ShieldCheck,
        ShieldAlert,
        FileText,
        Database,
        Clock,
        RotateCw,
        Activity,
        HardDrive,
        Cloud,
        ArrowRight,
        EyeOff,
        FolderTree,
        CassetteTape,
        LayoutDashboard,
        Zap
    } from 'lucide-svelte';
    import { Card } from '$lib/components/ui/card';
    import { Button } from '$lib/components/ui/button';
    import { getDashboardStatsSystemDashboardStatsGet, triggerScanSystemScanPost, triggerIndexingSystemIndexHashPost, type DashboardStatsSchema } from '$lib/api';
    import { cn, formatLocalDate, formatLocalTime } from '$lib/utils';
    import { toast } from 'svelte-sonner';

    let stats = $state<DashboardStatsSchema | null>(null);
    let loading = $state(true);
    let scanning = $state(false);
    let indexing = $state(false);

    async function loadStats() {
        loading = true;
        try {
            const response = await getDashboardStatsSystemDashboardStatsGet();
            if (response.data) {
                stats = response.data;
            }
        } catch (error) {
            console.error("Failed to load dashboard stats:", error);
        } finally {
            loading = false;
        }
    }

    async function startIndexing() {
        indexing = true;
        try {
            await triggerIndexingSystemIndexHashPost();
            toast.success("Background indexing job initiated");
        } catch (error: any) {
            toast.error(error.body?.detail || "Failed to start indexing");
        } finally {
            indexing = false;
        }
    }

    async function startScan() {
        scanning = true;
        try {
            await triggerScanSystemScanPost();
            toast.success("Scan job initiated successfully");
        } catch (error: any) {
            toast.error(error.body?.detail || "Failed to start scan");
        } finally {
            scanning = false;
        }
    }

    onMount(loadStats);

    function formatSize(bytes: number) {
        if (bytes === 0) return "0 B";
        const units = ["B", "KB", "MB", "GB", "TB", "PB"];
        let unitIndex = 0;
        let size = bytes;
        while (size >= 1024 && unitIndex < units.length - 1) {
            size /= 1024;
            unitIndex++;
        }
        return `${size.toFixed(1)} ${units[unitIndex]}`;
    }
</script>

<svelte:head>
    <title>Overview - TapeHoard</title>
</svelte:head>

<div class="flex flex-col gap-8 animate-in fade-in duration-700">
    <!-- Header -->
    <header class="flex justify-between items-center bg-bg-secondary px-8 py-5 rounded-xl border border-border-color shadow-2xl relative overflow-hidden">
        <div class="absolute inset-0 bg-gradient-to-r from-blue-500/5 to-transparent pointer-events-none"></div>
        <div class="relative z-10">
            <h1 class="text-2xl font-black uppercase tracking-tighter text-text-primary flex items-center gap-3">
                <LayoutDashboard class="text-blue-500" size={28} />
                Overview
            </h1>
            <p class="text-[12px] font-bold uppercase tracking-widest text-text-secondary mt-1 opacity-80">
                System Status & Statistics
            </p>
        </div>

        <div class="flex gap-3 z-10">
            <Button variant="outline" class="h-10 px-6 font-black uppercase tracking-widest text-[10px] border-border-color" onclick={loadStats}>
                <RotateCw size={14} class={cn("mr-2", loading && "animate-spin")} /> Refresh
            </Button>
            <Button variant="outline" class="h-10 px-6 font-black uppercase tracking-widest text-[10px] border-action-color/30 text-action-color hover:bg-action-color/5" onclick={startIndexing} disabled={indexing}>
                {#if indexing}
                    <RotateCw size={14} class="mr-2 animate-spin" /> Starting...
                {:else}
                    <Zap size={14} class="mr-2" /> Calculate Missing Hashes
                {/if}
            </Button>
            <Button variant="default" class="h-10 px-6 font-black uppercase tracking-widest text-[10px]" onclick={startScan} disabled={scanning}>
                {#if scanning}
                    <RotateCw size={14} class="mr-2 animate-spin" /> Starting...
                {:else}
                    <Activity size={14} class="mr-2" /> Start Full Scan
                {/if}
            </Button>
        </div>
    </header>

    <div class="space-y-8">
        {#if loading && !stats}
            <div class="h-96 bg-bg-secondary animate-pulse rounded-xl border border-border-color/50"></div>
        {:else if stats}
            <!-- MAIN GRID -->
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
                <!-- Archive Health -->
                <Card class="lg:col-span-2 p-8 bg-bg-secondary border-border-color shadow-xl overflow-hidden relative">
                    <div class="absolute top-0 right-0 p-8 opacity-5 text-blue-500">
                        <ShieldCheck size={200} />
                    </div>

                    <h3 class="text-lg font-black uppercase tracking-tighter text-text-primary mb-10 flex items-center gap-2">
                        <ShieldCheck size={18} class="text-blue-500" />
                        Archive Health
                    </h3>

                    <div class="grid grid-cols-2 gap-x-12 gap-y-10 relative z-10">
                        <div class="space-y-4">
                            <div>
                                <span class="text-[10px] font-black uppercase tracking-widest text-text-secondary opacity-50 block mb-1">Discovered Files</span>
                                <h4 class="text-4xl font-black text-text-primary mono tracking-tighter">{stats.total_files_indexed.toLocaleString()}</h4>
                                <p class="text-[9px] font-bold text-text-secondary uppercase mt-2">TOTAL OBJECTS IN INDEX</p>
                            </div>
                        </div>

                        <div class="space-y-4">
                            <div>
                                <span class="text-[10px] font-black uppercase tracking-widest text-text-secondary opacity-50 block mb-1">Hashed File Count</span>
                                <h4 class="text-4xl font-black text-text-primary mono tracking-tighter">
                                    {stats.hashed_files_count.toLocaleString()}
                                    <span class="text-sm font-bold text-text-secondary opacity-30">/ {stats.total_files_indexed.toLocaleString()}</span>
                                </h4>
                                <div class="w-full bg-bg-primary h-1.5 mt-3 rounded-full border border-border-color overflow-hidden">
                                    <div class="bg-blue-500 h-full transition-all duration-1000" style="width: {(stats.hashed_files_count / (stats.total_files_indexed || 1)) * 100}%"></div>
                                </div>
                            </div>
                        </div>

                        <div class="space-y-4">
                            <div>
                                <span class="text-[10px] font-black uppercase tracking-widest text-text-secondary opacity-50 block mb-1">Vulnerable Data</span>
                                <h4 class="text-4xl font-black text-error-color mono tracking-tighter">{formatSize(stats.unprotected_data_size)}</h4>
                                <p class="text-[9px] font-bold text-text-secondary uppercase mt-2">BYTES PENDING ARCHIVAL</p>
                            </div>
                        </div>

                        <div class="space-y-4">
                            <div>
                                <span class="text-[10px] font-black uppercase tracking-widest text-text-secondary opacity-50 block mb-1">Vulnerable Objects</span>
                                <h4 class="text-4xl font-black text-error-color mono tracking-tighter">{stats.unprotected_files_count.toLocaleString()}</h4>
                                <p class="text-[9px] font-bold text-text-secondary uppercase mt-2">OBJECTS PENDING ARCHIVAL</p>
                            </div>
                        </div>
                    </div>

                    <div class="mt-12 pt-8 border-t border-border-color/30 grid grid-cols-2 gap-8">
                        <div class="flex items-center gap-4">
                            <div class="p-2 bg-text-secondary/10 rounded-lg text-text-secondary">
                                <Clock size={20} />
                            </div>
                            <div>
                                <span class="text-[9px] font-black uppercase tracking-widest text-text-secondary opacity-50 block">Last Complete Scan</span>
                                <span class="text-xs font-black text-text-primary uppercase mono">
                                    {#if stats.last_scan_time}
                                        {formatLocalTime(stats.last_scan_time)} • {formatLocalDate(stats.last_scan_time)}
                                    {:else}
                                        STATION NEVER SCANNED
                                    {/if}
                                </span>
                            </div>
                        </div>
                        <div class="flex items-center gap-4">
                            <div class="p-2 bg-success-color/10 rounded-lg text-success-color">
                                <ShieldCheck size={20} />
                            </div>
                            <div>
                                <span class="text-[9px] font-black uppercase tracking-widest text-text-secondary opacity-50 block">Redundancy Ratio</span>
                                <span class="text-xs font-black text-success-color mono uppercase">{stats.redundancy_ratio}% REPLICATION</span>
                            </div>
                        </div>
                    </div>
                </Card>

                <!-- Quick Actions & Media -->
                <div class="space-y-8">
                    <Card class="p-8 bg-bg-secondary border-border-color shadow-xl h-fit">
                        <h3 class="text-lg font-black uppercase tracking-tighter text-text-primary mb-6">Quick Actions</h3>
                        <div class="space-y-3">
                            <Button variant="outline" class="w-full justify-between h-12 font-black uppercase tracking-widest text-[10px] border-border-color hover:border-blue-500/50 hover:bg-blue-500/5 group" href="/tracking">
                                Review Tracking Rules <ArrowRight size={14} class="group-hover:translate-x-1 transition-transform" />
                            </Button>
                            <Button variant="outline" class="w-full justify-between h-12 font-black uppercase tracking-widest text-[10px] border-border-color hover:border-success-color/50 hover:bg-success-color/5 group" href="/index-browser">
                                Browse Virtual Index <ArrowRight size={14} class="group-hover:translate-x-1 transition-transform" />
                            </Button>
                            <Button variant="outline" class="w-full justify-between h-12 font-black uppercase tracking-widest text-[10px] border-border-color hover:border-action-color/50 hover:bg-action-color/5 group" href="/inventory">
                                Manage Media <ArrowRight size={14} class="group-hover:translate-x-1 transition-transform" />
                            </Button>
                        </div>
                    </Card>

                    <Card class="p-8 bg-bg-secondary border-border-color shadow-xl h-fit">
                        <h3 class="text-lg font-black uppercase tracking-tighter text-text-primary mb-6">Media distribution</h3>
                        <div class="space-y-6">
                            <div class="flex items-center gap-4">
                                <div class="w-10 h-10 bg-blue-500/10 rounded-lg flex items-center justify-center text-blue-500">
                                    <CassetteTape size={20} />
                                </div>
                                <div class="flex-1">
                                    <div class="flex justify-between mb-1">
                                        <span class="text-[10px] font-black uppercase tracking-widest text-text-primary">LTO Tapes</span>
                                        <span class="text-[10px] font-bold mono">{stats.media_distribution.LTO || 0} Items</span>
                                    </div>
                                    <div class="w-full bg-bg-primary h-1.5 rounded-full overflow-hidden">
                                        <div class="bg-blue-500 h-full" style="width: {stats.media_distribution.LTO > 0 ? 100 : 0}%"></div>
                                    </div>
                                </div>
                            </div>
                            <div class="flex items-center gap-4">
                                <div class="w-10 h-10 bg-yellow-500/10 rounded-lg flex items-center justify-center text-yellow-500">
                                    <HardDrive size={20} />
                                </div>
                                <div class="flex-1">
                                    <div class="flex justify-between mb-1">
                                        <span class="text-[10px] font-black uppercase tracking-widest text-text-primary">HDD Storage</span>
                                        <span class="text-[10px] font-bold mono">{stats.media_distribution.HDD || 0} Items</span>
                                    </div>
                                    <div class="w-full bg-bg-primary h-1.5 rounded-full overflow-hidden">
                                        <div class="bg-yellow-500 h-full" style="width: {stats.media_distribution.HDD > 0 ? 100 : 0}%"></div>
                                    </div>
                                </div>
                            </div>
                            <div class="flex items-center gap-4">
                                <div class="w-10 h-10 bg-green-500/10 rounded-lg flex items-center justify-center text-green-500">
                                    <Cloud size={20} />
                                </div>
                                <div class="flex-1">
                                    <div class="flex justify-between mb-1">
                                        <span class="text-[10px] font-black uppercase tracking-widest text-text-primary">Cloud Vaults</span>
                                        <span class="text-[10px] font-bold mono">{stats.media_distribution.Cloud || 0} Items</span>
                                    </div>
                                    <div class="w-full bg-bg-primary h-1.5 rounded-full overflow-hidden">
                                        <div class="bg-green-500 h-full" style="width: {stats.media_distribution.Cloud > 0 ? 100 : 0}%"></div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </Card>
                </div>
            </div>
        {/if}
    </div>
</div>
