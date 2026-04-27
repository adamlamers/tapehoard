<script lang="ts">
    import { onMount } from "svelte";
    import {
        Save,
        HardDrive,
        ListX,
        CalendarClock,
        Bell,
        Cpu,
        Trash2,
        Plus,
        Database,
        Monitor,
        RotateCw,
        ArrowRight,
        ShieldAlert,
        FolderSearch,
        Download,
        Upload,
        Terminal,
        Globe
    } from "lucide-svelte";
    import { Card } from "$lib/components/ui/card";
    import { Button } from "$lib/components/ui/button";
    import { Input } from "$lib/components/ui/input";
    import {
        getSystemSettingsSystemSettingsGet,
        updateSystemSettingSystemSettingsPost,
        testNotificationDispatchSystemNotificationsTestPost,
        exportDatabaseIndexSystemDatabaseExportGet,
        importDatabaseIndexSystemDatabaseImportPost
    } from "$lib/api";
    import { toast } from "svelte-sonner";
    import { cn } from "$lib/utils";
    import { beforeNavigate } from '$app/navigation';
    import type { Navigation } from '@sveltejs/kit';

    let sourceRoots = $state<string[]>(["/source_data"]);
    let restoreDestinations = $state<string[]>(["/restores"]);
    let tapeDrives = $state<string[]>(["/dev/nst0"]);
    let globalExclusions = $state("");
    let scanSchedule = $state("");
    let archivalSchedule = $state("");
    let notificationUrls = $state<string[]>([]);

    let initialState = $state("");
    const isDirty = $derived(initialState !== JSON.stringify({
        sourceRoots,
        restoreDestinations,
        tapeDrives,
        globalExclusions,
        scanSchedule,
        archivalSchedule,
        notificationUrls
    }));

    beforeNavigate((navigation: any) => {
        if (isDirty) {
            if (!confirm("You have unsaved changes. Are you sure you want to leave?")) {
                navigation.cancel();
            }
        }
    });

    $effect(() => {
        const handleBeforeUnload = (e: BeforeUnloadEvent) => {
            if (isDirty) {
                e.preventDefault();
                e.returnValue = "";
            }
        };
        window.addEventListener('beforeunload', handleBeforeUnload);
        return () => window.removeEventListener('beforeunload', handleBeforeUnload);
    });

    let activeTab = $state("hardware");
    let loading = $state(true);
    let saving = $state(false);
    let exporting = $state(false);
    let importing = $state(false);

    // Path Picker state
    let pickerType = $state<"root" | "dest" | null>(null);
    let pickerIndex = $state<number | null>(null);

    const commonExclusions = [
        { label: "Git Objects", pattern: ".git/" },
        { label: "Node Modules", pattern: "node_modules/" },
        { label: "macOS Junk", pattern: ".DS_Store" },
        { label: "Windows Junk", pattern: "Thumbs.db" },
        { label: "Generic Cache", pattern: "Cache/" },
        { label: "Temporary Files", pattern: "*.tmp" },
        { label: "Python Cache", pattern: "__pycache__/" },
        { label: "Docker Files", pattern: "docker-compose.yml" },
        { label: "Build Output", pattern: "dist/" },
    ];

    function addCommonExclusion(pattern: string) {
        if (!globalExclusions.includes(pattern)) {
            globalExclusions = (globalExclusions.trim() + "\n" + pattern).trim() + "\n";
        }
    }

    const tabs = [
        { id: "hardware", label: "Drives", icon: Monitor },
        { id: "paths", label: "Storage Paths", icon: HardDrive },
        { id: "exclusions", label: "Exclusions", icon: ListX },
        { id: "scheduling", label: "Scheduling", icon: CalendarClock },
        { id: "notifications", label: "Alerting", icon: Bell },
        { id: "system", label: "System", icon: Cpu },
    ];

    async function loadSettings() {
        loading = true;
        try {
            const response = await getSystemSettingsSystemSettingsGet();
            if (response.data) {
                const data = response.data;
                if (data.source_roots) sourceRoots = JSON.parse(data.source_roots);
                if (data.restore_destinations) restoreDestinations = JSON.parse(data.restore_destinations);
                if (data.tape_drives) tapeDrives = JSON.parse(data.tape_drives);
                if (data.global_exclusions) globalExclusions = data.global_exclusions;
                if (data.schedule_scan) scanSchedule = data.schedule_scan;
                if (data.schedule_archival) archivalSchedule = data.schedule_archival;
                if (data.notification_urls) notificationUrls = JSON.parse(data.notification_urls);
            }

            // Capture snapshot for dirty check
            initialState = JSON.stringify({
                sourceRoots,
                restoreDestinations,
                tapeDrives,
                globalExclusions,
                scanSchedule,
                archivalSchedule,
                notificationUrls
            });
        } catch (error) {
            toast.error("Failed to load system configuration");
        } finally {
            loading = false;
        }
    }

    async function saveSettings() {
        saving = true;
        try {
            await Promise.all([
                updateSystemSettingSystemSettingsPost({ body: { key: "source_roots", value: JSON.stringify(sourceRoots) } }),
                updateSystemSettingSystemSettingsPost({ body: { key: "restore_destinations", value: JSON.stringify(restoreDestinations) } }),
                updateSystemSettingSystemSettingsPost({ body: { key: "tape_drives", value: JSON.stringify(tapeDrives) } }),
                updateSystemSettingSystemSettingsPost({ body: { key: "global_exclusions", value: globalExclusions } }),
                updateSystemSettingSystemSettingsPost({ body: { key: "schedule_scan", value: scanSchedule } }),
                updateSystemSettingSystemSettingsPost({ body: { key: "schedule_archival", value: archivalSchedule } }),
                updateSystemSettingSystemSettingsPost({ body: { key: "notification_urls", value: JSON.stringify(notificationUrls) } })
            ]);

            // Snapshot saved state
            initialState = JSON.stringify({
                sourceRoots,
                restoreDestinations,
                tapeDrives,
                globalExclusions,
                scanSchedule,
                archivalSchedule,
                notificationUrls
            });

            toast.success("System configuration committed");
        } catch (error) {
            toast.error("Failed to save settings");
        } finally {
            saving = false;
        }
    }

    async function handleExport() {
        exporting = true;
        try {
            const response = await exportDatabaseIndexSystemDatabaseExportGet();
            if (response.data) {
                const blob = await (response.data as any).blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `tapehoard_export_${new Date().toISOString().split('T')[0]}.db`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                toast.success("Database exported successfully");
            }
        } catch (error) {
            toast.error("Export failed");
        } finally {
            exporting = false;
        }
    }

    async function testNotify(url: string) {
        try {
            await testNotificationDispatchSystemNotificationsTestPost({ body: { url } });
            toast.success("Test notification dispatched");
        } catch (error) {
            toast.error("Notification test failed");
        }
    }

    function addSource() { sourceRoots = [...sourceRoots, ""]; }
    function removeSource(i: number) { sourceRoots = sourceRoots.filter((_, idx) => idx !== i); }
    function addDest() { restoreDestinations = [...restoreDestinations, ""]; }
    function removeDest(i: number) { restoreDestinations = restoreDestinations.filter((_, idx) => idx !== i); }
    function addDrive() { tapeDrives = [...tapeDrives, ""]; }
    function removeDrive(i: number) { tapeDrives = tapeDrives.filter((_, idx) => idx !== i); }
    function addNotify() { notificationUrls = [...notificationUrls, ""]; }
    function removeNotify(i: number) { notificationUrls = notificationUrls.filter((_, idx) => idx !== i); }

    onMount(loadSettings);
</script>

<svelte:head>
    <title>System Settings - TapeHoard</title>
</svelte:head>

<div class="flex flex-col h-full gap-8 animate-in fade-in duration-700">
    <header class="flex justify-between items-center bg-bg-secondary px-8 py-5 rounded-xl border border-border-color shadow-2xl relative overflow-hidden shrink-0">
        <div class="absolute inset-0 bg-gradient-to-r from-blue-500/5 to-transparent pointer-events-none"></div>
        <div class="relative z-10">
            <h1 class="text-2xl font-black uppercase tracking-tighter text-text-primary flex items-center gap-3">
                <Database class="text-blue-500" size={28} />
                Station Settings
            </h1>
            <p class="text-[12px] font-bold uppercase tracking-widest text-text-secondary mt-1 opacity-80">Configure archival logic & hardware</p>
        </div>

        <div class="z-10">
            <Button variant="default" size="lg" class="px-8 h-12 font-black uppercase tracking-widest text-[11px] shadow-lg shadow-blue-500/10" onclick={saveSettings} disabled={saving || !isDirty}>
                {#if saving}
                    <RotateCw size={18} class="mr-2 animate-spin" /> Saving...
                {:else}
                    <Save size={18} class="mr-2" /> Save Configuration
                {/if}
            </Button>
        </div>
    </header>

    <div class="flex flex-col lg:flex-row gap-8 flex-1 overflow-hidden min-h-0">
        <!-- Sidebar Navigation -->
        <nav class="w-full lg:w-64 flex lg:flex-col gap-1 shrink-0 overflow-x-auto lg:overflow-x-visible pb-2 lg:pb-0">
            {#each tabs as tab}
                <button
                    class={cn(
                        "flex items-center gap-3 px-5 py-4 rounded-xl text-[11px] font-black uppercase tracking-widest transition-all whitespace-nowrap",
                        activeTab === tab.id
                            ? "bg-blue-500/10 text-blue-500 border border-blue-500/20 shadow-[0_0_15px_rgba(59,130,246,0.1)]"
                            : "text-text-secondary hover:bg-white/5 border border-transparent"
                    )}
                    onclick={() => activeTab = tab.id}
                >
                    <tab.icon size={18} />
                    {tab.label}
                </button>
            {/each}
        </nav>

        <!-- Tab Content -->
        <main class="flex-1 overflow-y-auto pr-2 pb-12">
            {#if loading}
                <div class="h-96 bg-bg-secondary animate-pulse rounded-xl border border-border-color/50"></div>
            {:else}
                {#if activeTab === 'hardware'}
                    <div class="animate-in slide-in-from-bottom-4 duration-500">
                        <Card class="p-8 bg-bg-secondary border-border-color shadow-xl">
                            <div class="flex items-center gap-4 mb-8">
                                <div class="p-3 bg-blue-500/10 rounded-xl text-blue-500 border border-blue-500/20"><Monitor size={24} /></div>
                                <div>
                                    <h3 class="text-xl font-black text-text-primary uppercase tracking-tight">LTO Hardware</h3>
                                    <p class="text-[11px] text-text-secondary font-medium uppercase tracking-wider opacity-60">Define tape drive device nodes</p>
                                </div>
                            </div>
                            <div class="space-y-4">
                                {#each tapeDrives as drive, i}
                                    <div class="flex gap-3 animate-in slide-in-from-left-4 duration-300" style="animation-delay: {i * 50}ms">
                                        <div class="relative flex-1">
                                            <Terminal size={16} class="absolute left-4 top-3.5 text-text-secondary opacity-50" />
                                            <Input bind:value={tapeDrives[i]} placeholder="/dev/nst0" class="h-12 bg-bg-primary/50 pl-12 border-border-color font-mono text-sm" />
                                        </div>
                                        <Button variant="ghost" class="h-12 w-12 rounded-xl bg-error-color/5 text-error-color/60 hover:bg-error-color/10 hover:text-error-color" onclick={() => removeDrive(i)}><Trash2 size={18} /></Button>
                                    </div>
                                {/each}
                                <Button variant="outline" class="w-full h-14 border-dashed border-2 border-border-color hover:border-blue-500/50 hover:bg-blue-500/5 font-black uppercase tracking-widest text-[11px] mt-4" onclick={addDrive}>
                                    <Plus size={18} class="mr-2" /> Add Tape Drive
                                </Button>
                            </div>
                        </Card>
                    </div>

                {:else if activeTab === 'paths'}
                    <div class="animate-in slide-in-from-bottom-4 duration-500 space-y-8">
                        <Card class="p-8 bg-bg-secondary border-border-color shadow-xl">
                            <div class="flex items-center gap-4 mb-8">
                                <div class="p-3 bg-blue-500/10 rounded-xl text-blue-500 border border-blue-500/20"><HardDrive size={24} /></div>
                                <div>
                                    <h3 class="text-xl font-black text-text-primary uppercase tracking-tight">Source Roots</h3>
                                    <p class="text-[11px] text-text-secondary font-medium uppercase tracking-wider opacity-60">Directories available for archival</p>
                                </div>
                            </div>
                            <div class="space-y-4">
                                {#each sourceRoots as root, i}
                                    <div class="flex gap-3">
                                        <Input bind:value={sourceRoots[i]} placeholder="/mnt/data" class="h-12 bg-bg-primary/50 border-border-color font-mono text-sm" />
                                        <Button variant="ghost" class="h-12 w-12 rounded-xl bg-error-color/5 text-error-color/60 hover:bg-error-color/10 hover:text-error-color" onclick={() => removeSource(i)}><Trash2 size={18} /></Button>
                                    </div>
                                {/each}
                                <Button variant="outline" class="w-full h-14 border-dashed border-2 border-border-color font-black uppercase tracking-widest text-[11px]" onclick={addSource}><Plus size={18} class="mr-2" /> Add Source Root</Button>
                            </div>
                        </Card>

                        <Card class="p-8 bg-bg-secondary border-border-color shadow-xl">
                            <div class="flex items-center gap-4 mb-8">
                                <div class="p-3 bg-green-500/10 rounded-xl text-green-500 border border-green-500/20"><ArrowRight size={24} /></div>
                                <div>
                                    <h3 class="text-xl font-black text-text-primary uppercase tracking-tight">Restore Targets</h3>
                                    <p class="text-[11px] text-text-secondary font-medium uppercase tracking-wider opacity-60">Permitted recovery destinations</p>
                                </div>
                            </div>
                            <div class="space-y-4">
                                {#each restoreDestinations as dest, i}
                                    <div class="flex gap-3">
                                        <Input bind:value={restoreDestinations[i]} placeholder="/restores" class="h-12 bg-bg-primary/50 border-border-color font-mono text-sm" />
                                        <Button variant="ghost" class="h-12 w-12 rounded-xl bg-error-color/5 text-error-color/60 hover:bg-error-color/10 hover:text-error-color" onclick={() => removeDest(i)}><Trash2 size={18} /></Button>
                                    </div>
                                {/each}
                                <Button variant="outline" class="w-full h-14 border-dashed border-2 border-border-color font-black uppercase tracking-widest text-[11px]" onclick={addDest}><Plus size={18} class="mr-2" /> Add Restore Path</Button>
                            </div>
                        </Card>
                    </div>

                {:else if activeTab === 'exclusions'}
                    <div class="animate-in slide-in-from-bottom-4 duration-500">
                        <Card class="p-8 shadow-xl border-border-color/60 bg-bg-secondary">
                            <div class="flex items-center gap-4 mb-8">
                                <div class="p-3 bg-orange-500/10 rounded-xl text-orange-500 border border-orange-500/20"><ListX size={24} /></div>
                                <div>
                                    <h3 class="text-xl font-black text-text-primary uppercase tracking-tight">Exclusion Policy</h3>
                                    <p class="text-[11px] text-text-secondary font-medium uppercase tracking-wider opacity-60">Git-style ignore patterns for all scans.</p>
                                </div>
                            </div>
                            <div class="space-y-6">
                                <textarea
                                    bind:value={globalExclusions}
                                    class="w-full h-64 bg-bg-primary/50 border border-border-color rounded-2xl p-6 font-mono text-sm text-text-primary focus:ring-2 focus:ring-orange-500/20 focus:border-orange-500/40 transition-all outline-none resize-none"
                                    placeholder="Add one pattern per line (e.g. .git/)"
                                ></textarea>

                                <div class="space-y-3">
                                    <h4 class="text-[10px] font-black uppercase tracking-widest text-text-secondary opacity-40">Common Patterns</h4>
                                    <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
                                        {#each commonExclusions as item}
                                            <button
                                                class="flex items-center justify-between px-3 py-2 bg-bg-primary/40 border border-border-color/60 rounded-lg hover:border-orange-500/40 hover:bg-orange-500/5 transition-all group"
                                                onclick={() => addCommonExclusion(item.pattern)}
                                            >
                                                <span class="text-[10px] font-bold text-text-secondary group-hover:text-text-primary">{item.label}</span>
                                                <Plus size={10} class="text-text-secondary opacity-20 group-hover:opacity-100" />
                                            </button>
                                        {/each}
                                    </div>
                                </div>

                                <div class="p-5 bg-orange-500/5 border border-dashed border-orange-500/30 rounded-xl flex gap-4 items-start">
                                    <ShieldAlert size={24} class="text-orange-500 shrink-0 mt-0.5" />
                                    <div class="space-y-1">
                                        <span class="text-xs font-black uppercase text-orange-500 tracking-widest">Policy Warning</span>
                                        <p class="text-[11px] text-text-secondary leading-relaxed font-medium">Broad exclusion patterns can result in critical data being skipped during the archival process. Ensure patterns match only transient data.</p>
                                    </div>
                                </div>
                            </div>
                        </Card>
                    </div>

                {:else if activeTab === 'scheduling'}
                    <div class="animate-in slide-in-from-bottom-4 duration-500 space-y-8">
                        <Card class="p-8 bg-bg-secondary border-border-color shadow-xl">
                            <div class="flex items-center gap-4 mb-8">
                                <div class="p-3 bg-blue-500/10 rounded-xl text-blue-500 border border-blue-500/20"><CalendarClock size={24} /></div>
                                <div>
                                    <h3 class="text-xl font-black text-text-primary uppercase tracking-tight">Scan Frequency</h3>
                                    <p class="text-[11px] text-text-secondary font-medium uppercase tracking-wider opacity-60">Scheduled system discovery policy</p>
                                </div>
                            </div>
                            <div class="flex gap-4">
                                <div class="relative flex-1">
                                    <Terminal size={16} class="absolute left-4 top-3.5 text-text-secondary opacity-50" />
                                    <Input bind:value={scanSchedule} placeholder="0 2 * * *" class="h-12 bg-bg-primary/50 pl-12 border-border-color font-mono text-sm" />
                                </div>
                                <div class="flex gap-2">
                                    <Button variant="outline" class="h-12 px-4 text-[10px] uppercase font-black tracking-widest" onclick={() => scanSchedule = "0 * * * *"}>Hourly</Button>
                                    <Button variant="outline" class="h-12 px-4 text-[10px] uppercase font-black tracking-widest" onclick={() => scanSchedule = "0 2 * * *"}>Daily</Button>
                                </div>
                            </div>
                        </Card>

                        <Card class="p-8 bg-bg-secondary border-border-color shadow-xl">
                            <div class="flex items-center gap-4 mb-8">
                                <div class="p-3 bg-action-color/10 rounded-xl text-action-color border border-action-color/20"><CalendarClock size={24} /></div>
                                <div>
                                    <h3 class="text-xl font-black text-text-primary uppercase tracking-tight">Archival Frequency</h3>
                                    <p class="text-[11px] text-text-secondary font-medium uppercase tracking-wider opacity-60">Scheduled media ingestion policy</p>
                                </div>
                            </div>
                            <div class="flex gap-4">
                                <div class="relative flex-1">
                                    <Terminal size={16} class="absolute left-4 top-3.5 text-text-secondary opacity-50" />
                                    <Input bind:value={archivalSchedule} placeholder="0 4 * * 0" class="h-12 bg-bg-primary/50 pl-12 border-border-color font-mono text-sm" />
                                </div>
                                <div class="flex gap-2">
                                    <Button variant="outline" class="h-12 px-4 text-[10px] uppercase font-black tracking-widest" onclick={() => archivalSchedule = "0 4 * * 0"}>Weekly</Button>
                                    <Button variant="outline" class="h-12 px-4 text-[10px] uppercase font-black tracking-widest" onclick={() => archivalSchedule = "0 4 1 * *"}>Monthly</Button>
                                </div>
                            </div>
                        </Card>
                    </div>

                {:else if activeTab === 'notifications'}
                    <div class="animate-in slide-in-from-bottom-4 duration-500">
                        <Card class="p-8 bg-bg-secondary border-border-color shadow-xl">
                            <div class="flex items-center gap-4 mb-8">
                                <div class="p-3 bg-blue-500/10 rounded-xl text-blue-500 border border-blue-500/20"><Bell size={24} /></div>
                                <div>
                                    <h3 class="text-xl font-black text-text-primary uppercase tracking-tight">Alerting Endpoints</h3>
                                    <p class="text-[11px] text-text-secondary font-medium uppercase tracking-wider opacity-60">Apprise-compatible notification URLs</p>
                                </div>
                            </div>
                            <div class="space-y-4">
                                {#each notificationUrls as url, i}
                                    <div class="flex gap-3">
                                        <div class="relative flex-1">
                                            <Globe size={16} class="absolute left-4 top-3.5 text-text-secondary opacity-50" />
                                            <Input bind:value={notificationUrls[i]} placeholder="prowl://apikey" class="h-12 bg-bg-primary/50 pl-12 border-border-color font-mono text-sm" />
                                        </div>
                                        <Button variant="outline" class="h-12 px-4 text-[10px] uppercase font-black tracking-widest border-border-color" onclick={() => testNotify(notificationUrls[i])}>Test</Button>
                                        <Button variant="ghost" class="h-12 w-12 rounded-xl bg-error-color/5 text-error-color/60 hover:bg-error-color/10 hover:text-error-color" onclick={() => removeNotify(i)}><Trash2 size={18} /></Button>
                                    </div>
                                {/each}
                                <Button variant="outline" class="w-full h-14 border-dashed border-2 border-border-color font-black uppercase tracking-widest text-[11px]" onclick={addNotify}><Plus size={18} class="mr-2" /> Add Notification Endpoint</Button>
                            </div>
                        </Card>
                    </div>

                {:else if activeTab === 'system'}
                    <div class="animate-in slide-in-from-bottom-4 duration-500 space-y-8">
                        <Card class="p-8 bg-bg-secondary border-border-color shadow-xl">
                            <div class="flex items-center gap-4 mb-8">
                                <div class="p-3 bg-blue-500/10 rounded-xl text-blue-500 border border-blue-500/20"><Database size={24} /></div>
                                <div>
                                    <h3 class="text-xl font-black text-text-primary uppercase tracking-tight">Index Management</h3>
                                    <p class="text-[11px] text-text-secondary font-medium uppercase tracking-wider opacity-60">Backup and restore the system state</p>
                                </div>
                            </div>
                            <div class="grid grid-cols-2 gap-6">
                                <Button variant="outline" class="h-16 font-black uppercase tracking-widest text-[11px] border-border-color hover:bg-blue-500/5 group" onclick={handleExport} disabled={exporting}>
                                    {#if exporting}
                                        <RotateCw size={20} class="mr-3 animate-spin" /> Compiling...
                                    {:else}
                                        <Download size={20} class="mr-3 text-blue-400 group-hover:scale-110 transition-transform" /> Export Database Index
                                    {/if}
                                </Button>
                                <Button variant="outline" class="h-16 font-black uppercase tracking-widest text-[11px] border-border-color hover:bg-orange-500/5 group opacity-50 cursor-not-allowed">
                                    <Upload size={20} class="mr-3 text-orange-400" /> Import Index (Restricted)
                                </Button>
                            </div>
                        </Card>
                    </div>
                {/if}
            {/if}
        </main>
    </div>
</div>
