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

<div class="flex flex-col gap-6 animate-in fade-in duration-700">
    <!-- Header -->
    <header class="flex justify-between items-center bg-bg-secondary px-6 py-4 rounded-xl border border-border-color shadow-2xl relative overflow-hidden">
        <div class="absolute inset-0 bg-gradient-to-r from-blue-500/5 to-transparent pointer-events-none"></div>
        <div class="relative z-10">
            <h1 class="text-xl font-bold text-text-primary flex items-center gap-3">
                <LayoutDashboard class="text-blue-500" size={24} />
                Overview
            </h1>
            <p class="text-4xs font-medium text-text-secondary mt-1 opacity-80">
                System status & statistics
            </p>
        </div>

        <div class="flex gap-2 z-10">
            <Button variant="outline" class="h-10 px-5 font-semibold text-xs border-border-color" onclick={loadStats}>
                <RotateCw size={14} class={cn("mr-2", loading && "animate-spin")} /> Refresh
            </Button>
            <Button variant="outline" class="h-10 px-5 font-semibold text-xs border-action-color/30 text-action-color hover:bg-action-color/5" onclick={startIndexing} disabled={indexing}>
                {#if indexing}
                    <RotateCw size={14} class="mr-2 animate-spin" /> Starting...
                {:else}
                    <Zap size={14} class="mr-2" /> Missing hashes
                {/if}
            </Button>
            <Button variant="default" class="h-10 px-5 font-semibold text-xs" onclick={startScan} disabled={scanning}>
                {#if scanning}
                    <RotateCw size={14} class="mr-2 animate-spin" /> Starting...
                {:else}
                    <Activity size={14} class="mr-2" /> Start scan
                {/if}
            </Button>
        </div>
    </header>

    <div class="space-y-6">
        {#if loading && !stats}
            <div class="h-80 bg-bg-secondary animate-pulse rounded-xl border border-border-color/50"></div>
        {:else if stats}
            <!-- MAIN GRID -->
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <!-- Archive Health -->
                <Card class="lg:col-span-2 p-6 bg-bg-secondary border-border-color shadow-xl overflow-hidden relative">
                    <div class="absolute top-0 right-0 p-8 opacity-5 text-blue-500">
                        <ShieldCheck size={160} />
                    </div>

                    <h3 class="text-base font-bold text-text-primary mb-8 flex items-center gap-2">
                        <ShieldCheck size={18} class="text-blue-500" />
                        Archive health
                    </h3>

                    <div class="grid grid-cols-2 gap-x-12 gap-y-10 relative z-10">
                        <div class="space-y-4">
                            <div>
                                <span class="text-4xs font-bold uppercase text-text-secondary opacity-50 block mb-1">Monitored Files</span>
                                <h4 class="text-3xl font-bold text-text-primary mono">{stats.monitored_files_count.toLocaleString()}</h4>
                                <p class="text-5xs font-medium text-text-secondary uppercase mt-2">Objects tracked for archival</p>
                            </div>
                        </div>

                        <div class="space-y-4">
                            <div>
                                <span class="text-4xs font-bold uppercase text-text-secondary opacity-50 block mb-1">Hashed Files</span>
                                <h4 class="text-3xl font-bold text-text-primary mono">
                                    {stats.hashed_files_count.toLocaleString()}
                                    <span class="text-xs font-medium text-text-secondary opacity-30">/ {stats.monitored_files_count.toLocaleString()}</span>
                                </h4>
                                <div class="w-full bg-bg-primary h-1.5 mt-2.5 rounded-full border border-border-color overflow-hidden">
                                    <div class="bg-blue-500 h-full transition-all duration-1000" style="width: {(stats.hashed_files_count / (stats.monitored_files_count || 1)) * 100}%"></div>
                                </div>
                            </div>
                        </div>

                        <div class="space-y-4">
                            <div>
                                <span class="text-4xs font-bold uppercase text-text-secondary opacity-50 block mb-1">Ignored Objects</span>
                                <h4 class="text-3xl font-bold text-text-secondary mono">{stats.ignored_files_count.toLocaleString()}</h4>
                                <p class="text-5xs font-medium text-text-secondary uppercase mt-2">Objects excluded from policy</p>
                            </div>
                        </div>

                        <div class="space-y-4">
                            <div>
                                <span class="text-4xs font-bold uppercase text-text-secondary opacity-50 block mb-1">Archived Data</span>
                                <h4 class="text-3xl font-bold text-success-color mono">{formatSize(stats.archived_data_size)}</h4>
                                <p class="text-5xs font-medium text-text-secondary uppercase mt-2">Total unique bytes on media</p>
                            </div>
                        </div>

                        <div class="space-y-4">
                            <div>
                                <span class="text-4xs font-bold uppercase text-text-secondary opacity-50 block mb-1">Vulnerable Data</span>
                                <h4 class="text-3xl font-bold text-error-color mono">{formatSize(stats.unprotected_data_size)}</h4>
                                <p class="text-5xs font-medium text-text-secondary uppercase mt-2">Bytes pending archival</p>
                            </div>
                        </div>
                    </div>

                    <div class="mt-8 pt-6 border-t border-border-color/30 grid grid-cols-2 gap-6">
                        <div class="flex items-center gap-4">
                            <div class="p-2.5 bg-text-secondary/10 rounded-lg text-text-secondary">
                                <Clock size={18} />
                            </div>
                            <div>
                                <span class="text-5xs font-bold uppercase text-text-secondary opacity-50 block">Last Complete Scan</span>
                                <span class="text-xs font-semibold text-text-primary mono">
                                    {#if stats.last_scan_time}
                                        {formatLocalTime(stats.last_scan_time)} • {formatLocalDate(stats.last_scan_time)}
                                    {:else}
                                        Station never scanned
                                    {/if}
                                </span>
                            </div>
                        </div>
                        <div class="flex items-center gap-4">
                            <div class="p-2.5 bg-success-color/10 rounded-lg text-success-color">
                                <ShieldCheck size={18} />
                            </div>
                            <div>
                                <span class="text-5xs font-bold uppercase text-text-secondary opacity-50 block">Redundancy Ratio</span>
                                <span class="text-xs font-semibold text-success-color mono">{stats.redundancy_ratio}% replication</span>
                            </div>
                        </div>
                    </div>
                </Card>

                <!-- Quick Actions & Media -->
                <div class="space-y-6">
                    <Card class="p-6 bg-bg-secondary border-border-color shadow-xl h-fit">
                        <h3 class="text-base font-bold text-text-primary mb-5">Quick actions</h3>
                        <div class="space-y-2">
                            <Button variant="outline" class="w-full justify-between h-10 px-5 font-semibold text-xs border-border-color hover:border-blue-500/50 hover:bg-blue-500/5 group" href="/filesystem">
                                Review tracking rules <ArrowRight size={14} class="group-hover:translate-x-1 transition-transform" />
                            </Button>
                            <Button variant="outline" class="w-full justify-between h-10 px-5 font-semibold text-xs border-border-color hover:border-success-color/50 hover:bg-success-color/5 group" href="/index-browser">
                                Browse virtual index <ArrowRight size={14} class="group-hover:translate-x-1 transition-transform" />
                            </Button>
                            <Button variant="outline" class="w-full justify-between h-10 px-5 font-semibold text-xs border-border-color hover:border-action-color/50 hover:bg-action-color/5 group" href="/inventory">
                                Manage media <ArrowRight size={14} class="group-hover:translate-x-1 transition-transform" />
                            </Button>
                        </div>
                    </Card>

                    <Card class="p-6 bg-bg-secondary border-border-color shadow-xl h-fit">
                        <h3 class="text-base font-bold text-text-primary mb-5">Media distribution</h3>
                        <div class="space-y-5">
                            <div class="flex items-center gap-4">
                                <div class="w-9 h-9 bg-blue-500/10 rounded-lg flex items-center justify-center text-blue-500">
                                    <CassetteTape size={18} />
                                </div>
                                <div class="flex-1">
                                    <div class="flex justify-between mb-1">
                                        <span class="text-xs font-semibold text-text-primary">LTO Tapes</span>
                                        <span class="text-4xs font-medium mono">{stats.media_distribution.LTO || 0} items</span>
                                    </div>
                                    <div class="w-full bg-bg-primary h-1.5 rounded-full overflow-hidden">
                                        <div class="bg-blue-500 h-full" style="width: {stats.media_distribution.LTO > 0 ? 100 : 0}%"></div>
                                    </div>
                                </div>
                            </div>
                            <div class="flex items-center gap-4">
                                <div class="w-9 h-9 bg-yellow-500/10 rounded-lg flex items-center justify-center text-yellow-500">
                                    <HardDrive size={18} />
                                </div>
                                <div class="flex-1">
                                    <div class="flex justify-between mb-1">
                                        <span class="text-xs font-semibold text-text-primary">HDD Storage</span>
                                        <span class="text-4xs font-medium mono">{stats.media_distribution.HDD || 0} items</span>
                                    </div>
                                    <div class="w-full bg-bg-primary h-1.5 rounded-full overflow-hidden">
                                        <div class="bg-yellow-500 h-full" style="width: {stats.media_distribution.HDD > 0 ? 100 : 0}%"></div>
                                    </div>
                                </div>
                            </div>
                            <div class="flex items-center gap-4">
                                <div class="w-9 h-9 bg-green-500/10 rounded-lg flex items-center justify-center text-green-500">
                                    <Cloud size={18} />
                                </div>
                                <div class="flex-1">
                                    <div class="flex justify-between mb-1">
                                        <span class="text-xs font-semibold text-text-primary">Cloud Vaults</span>
                                        <span class="text-4xs font-medium mono">{stats.media_distribution.Cloud || 0} items</span>
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
