<script lang="ts">
    import { onMount } from 'svelte';
    import { Search, Save, ShieldAlert, FolderSearch, RotateCw, Plus, Trash2, Download, Database, Upload, CalendarClock, Zap, Bell, Send, Settings, HardDrive, ListX, FolderOpen, ArrowRight, Monitor } from 'lucide-svelte';
    import { Button } from '$lib/components/ui/button';
    import { Card } from '$lib/components/ui/card';
    import { Input } from '$lib/components/ui/input';
    import DirectoryPicker from '$lib/components/DirectoryPicker.svelte';
    import {
        getSystemSettingsSystemSettingsGet,
        updateSystemSettingSystemSettingsPost,
        exportDatabaseIndexSystemDatabaseExportGet,
        importDatabaseIndexSystemDatabaseImportPost,
        testNotificationDispatchSystemNotificationsTestPost
    } from '$lib/api';
    import { toast } from "svelte-sonner";
    import { cn } from "$lib/utils";

    let sourceRoots = $state<string[]>(["/source_data"]);
    let restoreDestinations = $state<string[]>(["/restores"]);
    let tapeDrives = $state<string[]>(["/dev/nst0"]);
    let globalExclusions = $state("*.tmp\nnode_modules/\n.DS_Store\nThumbs.db\nCache/\n");
    let scanSchedule = $state("");
    let archivalSchedule = $state("");
    let notificationUrls = $state<string[]>([]);

    let activeTab = $state("hardware");
    let loading = $state(true);
    let saving = $state(false);
    let exporting = $state(false);
    let importing = $state(false);
    let testingUrlIdx = $state<number | null>(null);

    // Path Picker state
    let pickerType = $state<"root" | "dest" | null>(null);
    let pickerIndex = $state<number | null>(null);

    const tabs = [
        { id: "hardware", label: "Tape Drives", icon: Monitor },
        { id: "paths", label: "Storage Paths", icon: HardDrive },
        { id: "exclusions", label: "Exclusions", icon: ListX },
        { id: "scheduling", label: "Scheduling", icon: CalendarClock },
        { id: "alerts", label: "Alerting", icon: Bell },
        { id: "export", label: "System Export", icon: Database },
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
            toast.success("System configuration committed");
        } catch (error) {
            toast.error("Failed to save settings");
        } finally {
            saving = false;
        }
    }

    async function handleTestNotification(url: string, index: number) {
        if (!url || !url.trim()) {
            toast.error("Please enter a URL first");
            return;
        }
        testingUrlIdx = index;
        try {
            await testNotificationDispatchSystemNotificationsTestPost({
                body: { url },
                throwOnError: true
            });
            toast.success("Test notification sent!");
        } catch (error: any) {
            toast.error(error.body?.detail || "Test failed");
        } finally {
            testingUrlIdx = null;
        }
    }

    async function handleBackup() {
        exporting = true;
        try {
            const url = "/system/database/export";
            window.location.href = url;
            toast.success("Database backup initiated");
        } catch (error) {
            toast.error("Failed to backup database");
        } finally {
            exporting = false;
        }
    }

    async function handleRestore(event: Event) {
        const input = event.target as HTMLInputElement;
        if (!input.files || input.files.length === 0) return;

        const file = input.files[0];
        if (!confirm(`Are you sure you want to restore "${file.name}"? This will overwrite your current index and ALL settings!`)) {
            input.value = "";
            return;
        }

        importing = true;
        try {
            await importDatabaseIndexSystemDatabaseImportPost({
                body: { file },
                throwOnError: true
            } as any);
            toast.success("Database restored successfully");
            setTimeout(() => window.location.reload(), 1500);
        } catch (error: any) {
            toast.error(error.body?.detail || "Failed to restore database");
        } finally {
            importing = false;
            input.value = "";
        }
    }

    function addRoot() { sourceRoots = [...sourceRoots, ""]; }
    function removeRoot(index: number) { sourceRoots = sourceRoots.filter((_, i) => i !== index); }
    function addDest() { restoreDestinations = [...restoreDestinations, ""]; }
    function removeDest(index: number) { restoreDestinations = restoreDestinations.filter((_, i) => i !== index); }
    function addDrive() { tapeDrives = [...tapeDrives, ""]; }
    function removeDrive(index: number) { tapeDrives = tapeDrives.filter((_, i) => i !== index); }
    function addNotificationUrl() { notificationUrls = [...notificationUrls, ""]; }
    function removeNotificationUrl(index: number) { notificationUrls = notificationUrls.filter((_, i) => i !== index); }

    function openPicker(type: "root" | "dest", index: number) {
        pickerType = type;
        pickerIndex = index;
    }

    function handlePathSelect(path: string) {
        if (pickerType === "root" && pickerIndex !== null) {
            sourceRoots[pickerIndex] = path;
        } else if (pickerType === "dest" && pickerIndex !== null) {
            restoreDestinations[pickerIndex] = path;
        }
        pickerType = null;
        pickerIndex = null;
    }

    onMount(loadSettings);
</script>

<svelte:head>
    <title>System Settings - TapeHoard</title>
</svelte:head>

<!-- Directory Picker Overlay -->
{#if pickerType}
    <DirectoryPicker
        onSelect={handlePathSelect}
        onCancel={() => pickerType = null}
    />
{/if}

<div class="flex flex-col gap-8 h-full overflow-hidden animate-in fade-in duration-700">
    <!-- Header -->
    <header class="flex justify-between items-center bg-bg-secondary px-8 py-5 rounded-xl border border-border-color shadow-2xl relative overflow-hidden shrink-0">
        <div class="absolute inset-0 bg-gradient-to-r from-orange-500/5 to-transparent pointer-events-none"></div>
        <div class="relative z-10">
            <h1 class="text-2xl font-black uppercase tracking-tighter text-text-primary flex items-center gap-3">
                <Settings class="text-orange-500" size={28} />
                System Settings
            </h1>
            <p class="text-[12px] font-bold uppercase tracking-widest text-text-secondary mt-1 opacity-80">
                Core Configuration & Disaster Recovery
            </p>
        </div>

        <Button variant="default" class="h-11 px-8 font-black uppercase tracking-widest text-[11px] z-10" onclick={saveSettings} disabled={saving}>
            {#if saving}
                <RotateCw size={18} class="mr-2 animate-spin" /> Committing...
            {:else}
                <Save size={18} class="mr-2" /> Commit Changes
            {/if}
        </Button>
    </header>

    {#if loading}
        <div class="flex-1 flex flex-col items-center justify-center gap-4 opacity-50">
            <RotateCw size={48} class="animate-spin text-orange-500" />
            <span class="text-xs font-black uppercase tracking-widest">Loading settings...</span>
        </div>
    {:else}
        <div class="flex-1 flex gap-8 min-h-0">
            <!-- Sidebar Navigation -->
            <aside class="w-64 flex flex-col gap-2 shrink-0">
                {#each tabs as tab}
                    <button
                        class={cn(
                            "flex items-center gap-3 px-6 py-4 rounded-xl text-[11px] font-black uppercase tracking-widest transition-all text-left border-2",
                            activeTab === tab.id
                                ? "bg-action-color/10 border-action-color text-text-primary shadow-lg shadow-action-color/10"
                                : "bg-bg-secondary border-transparent text-text-secondary hover:bg-white/5 hover:text-text-primary"
                        )}
                        onclick={() => activeTab = tab.id}
                    >
                        <tab.icon size={18} class={activeTab === tab.id ? "text-action-color" : "opacity-40"} />
                        {tab.label}
                    </button>
                {/each}
            </aside>

            <!-- Active Tab Content -->
            <div class="flex-1 min-w-0 overflow-y-auto pr-2 pb-12">
                {#if activeTab === 'hardware'}
                    <div class="animate-in slide-in-from-bottom-4 duration-500">
                        <Card class="p-8 shadow-xl border-border-color/60 bg-bg-secondary">
                            <div class="flex items-center justify-between mb-8">
                                <div class="flex items-center gap-4">
                                    <div class="p-3 bg-blue-500/10 rounded-xl text-blue-500 border border-blue-500/20"><Monitor size={24} /></div>
                                    <div>
                                        <h3 class="text-xl font-black text-text-primary uppercase tracking-tight">Tape Drives</h3>
                                        <p class="text-[11px] text-text-secondary font-medium uppercase tracking-wider opacity-60">Physical LTO hardware attached to the host.</p>
                                    </div>
                                </div>
                                <Button variant="outline" size="sm" class="h-9 text-[10px] font-black uppercase tracking-widest border-blue-500/30 text-blue-400" onclick={addDrive}><Plus size={14} class="mr-1" /> Add Drive</Button>
                            </div>
                            <div class="space-y-4">
                                {#each tapeDrives as drive, i}
                                    <div class="flex gap-3 group animate-in slide-in-from-left-2 duration-300">
                                        <Input bind:value={tapeDrives[i]} placeholder="/dev/nst0" class="h-12 bg-bg-primary/50 border-border-color font-mono text-sm focus:border-blue-500/50" />
                                        <Button variant="ghost" size="icon" class="h-12 w-12 hover:bg-error-color/10 hover:text-error-color" onclick={() => removeDrive(i)}><Trash2 size={18} /></Button>
                                    </div>
                                {/each}
                                {#if tapeDrives.length === 0}
                                    <div class="py-12 border-2 border-dashed border-border-color rounded-2xl flex flex-col items-center justify-center opacity-20">
                                        <Monitor size={48} class="mb-2" />
                                        <p class="text-[10px] font-black uppercase tracking-widest">No drives configured</p>
                                    </div>
                                {/if}
                            </div>
                        </Card>
                    </div>

                {:else if activeTab === 'paths'}
                    <div class="space-y-8 animate-in slide-in-from-bottom-4 duration-500">
                        <Card class="p-8 shadow-xl border-border-color/60 bg-bg-secondary">
                            <div class="flex items-center justify-between mb-8">
                                <div class="flex items-center gap-4">
                                    <div class="p-3 bg-orange-500/10 rounded-xl text-orange-500 border border-orange-500/20"><Search size={24} /></div>
                                    <div>
                                        <h3 class="text-xl font-black text-text-primary uppercase tracking-tight">Source Roots</h3>
                                        <p class="text-[11px] text-text-secondary font-medium uppercase tracking-wider opacity-60">Base directories to scan for backups.</p>
                                    </div>
                                </div>
                                <Button variant="outline" size="sm" class="h-9 text-[10px] font-black uppercase tracking-widest border-orange-500/30 text-orange-400" onclick={addRoot}><Plus size={14} class="mr-1" /> Add Root</Button>
                            </div>
                            <div class="space-y-4">
                                {#each sourceRoots as root, i}
                                    <div class="flex gap-3 group animate-in slide-in-from-left-2 duration-300">
                                        <div class="relative flex-1">
                                            <Input bind:value={sourceRoots[i]} placeholder="/mnt/data" class="h-12 bg-bg-primary/50 border-border-color font-mono text-sm focus:border-orange-500/50 pr-12" />
                                            <button
                                                class="absolute right-3 top-3 text-text-secondary hover:text-orange-400 transition-colors"
                                                onclick={() => openPicker("root", i)}
                                            >
                                                <FolderOpen size={20} />
                                            </button>
                                        </div>
                                        <Button variant="ghost" size="icon" class="h-12 w-12 hover:bg-error-color/10 hover:text-error-color" onclick={() => removeRoot(i)}><Trash2 size={18} /></Button>
                                    </div>
                                {/each}
                            </div>
                        </Card>

                        <Card class="p-8 shadow-xl border-border-color/60 bg-bg-secondary">
                            <div class="flex items-center justify-between mb-8">
                                <div class="flex items-center gap-4">
                                    <div class="p-3 bg-success-color/10 rounded-xl text-success-color border border-success-color/20"><Download size={24} /></div>
                                    <div>
                                        <h3 class="text-xl font-black text-text-primary uppercase tracking-tight">Recovery Targets</h3>
                                        <p class="text-[11px] text-text-secondary font-medium uppercase tracking-wider opacity-60">Host locations available for file recovery.</p>
                                    </div>
                                </div>
                                <Button variant="outline" size="sm" class="h-9 text-[10px] font-black uppercase tracking-widest border-success-color/30 text-success-color" onclick={addDest}><Plus size={14} class="mr-1" /> Add Target</Button>
                            </div>
                            <div class="space-y-4">
                                {#each restoreDestinations as dest, i}
                                    <div class="flex gap-3 group animate-in slide-in-from-right-2 duration-300">
                                        <div class="relative flex-1">
                                            <Input bind:value={restoreDestinations[i]} placeholder="/mnt/recovery" class="h-12 bg-bg-primary/50 border-border-color font-mono text-sm focus:border-success-color/50 pr-12" />
                                            <button
                                                class="absolute right-3 top-3 text-text-secondary hover:text-success-color transition-colors"
                                                onclick={() => openPicker("dest", i)}
                                            >
                                                <FolderOpen size={20} />
                                            </button>
                                        </div>
                                        <Button variant="ghost" size="icon" class="h-12 w-12 hover:bg-error-color/10 hover:text-error-color" onclick={() => removeDest(i)}><Trash2 size={18} /></Button>
                                    </div>
                                {/each}
                            </div>
                        </Card>
                    </div>

                {:else if activeTab === 'exclusions'}
                    <div class="animate-in slide-in-from-bottom-4 duration-500">
                        <Card class="p-8 shadow-xl border-border-color/60 bg-bg-secondary">
                            <div class="flex items-center gap-4 mb-8">
                                <div class="p-3 bg-orange-500/10 rounded-xl text-orange-500 border border-orange-500/20"><FolderSearch size={24} /></div>
                                <div>
                                    <h3 class="text-xl font-black text-text-primary uppercase tracking-tight">Global Exclusion Policy</h3>
                                    <p class="text-[11px] text-text-secondary font-medium uppercase tracking-wider opacity-60">Git-style ignore patterns for all scans.</p>
                                </div>
                            </div>
                            <div class="space-y-6">
                                <textarea
                                    bind:value={globalExclusions}
                                    class="w-full h-80 bg-bg-primary/50 border border-border-color rounded-2xl p-6 font-mono text-sm text-text-primary focus:ring-2 focus:ring-orange-500/20 focus:border-orange-500/40 transition-all outline-none resize-none"
                                    placeholder="*.tmp&#10;node_modules/&#10;.DS_Store"
                                ></textarea>
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
                    <div class="animate-in slide-in-from-bottom-4 duration-500">
                        <Card class="p-8 shadow-xl border-border-color/60 bg-bg-secondary">
                            <div class="flex items-center gap-4 mb-10">
                                <div class="p-3 bg-blue-500/10 rounded-xl text-blue-500 border border-blue-500/20"><CalendarClock size={24} /></div>
                                <div>
                                    <h3 class="text-xl font-black text-text-primary uppercase tracking-tight">Scheduling</h3>
                                    <p class="text-[11px] text-text-secondary font-medium uppercase tracking-wider opacity-60">Configure autonomous media discovery and archival.</p>
                                </div>
                            </div>
                            <div class="grid grid-cols-1 md:grid-cols-2 gap-12">
                                <div class="space-y-6">
                                    <div class="flex items-center gap-2">
                                        <Zap size={16} class="text-blue-400" />
                                        <span class="text-xs font-black uppercase tracking-widest text-text-primary">System Scan Frequency</span>
                                    </div>
                                    <div class="flex gap-2">
                                        <Input bind:value={scanSchedule} placeholder="0 2 * * *" class="h-12 bg-bg-primary/50 border-border-color font-mono text-sm" />
                                        <Button variant="outline" class="h-12 px-4 text-[10px] uppercase font-black tracking-widest" onclick={() => scanSchedule = "0 2 * * *"}>Daily</Button>
                                    </div>
                                    <p class="text-[10px] text-text-secondary italic leading-relaxed opacity-60">Standard Cron: minute hour day month day_of_week.</p>
                                </div>

                                <div class="space-y-6">
                                    <div class="flex items-center gap-2">
                                        <Zap size={16} class="text-success-color" />
                                        <span class="text-xs font-black uppercase tracking-widest text-text-primary">Media Archival Frequency</span>
                                    </div>
                                    <div class="flex gap-2">
                                        <Input bind:value={archivalSchedule} placeholder="0 4 * * 0" class="h-12 bg-bg-primary/50 border-border-color font-mono text-sm" />
                                        <Button variant="outline" class="h-12 px-4 text-[10px] uppercase font-black tracking-widest" onclick={() => archivalSchedule = "0 4 * * 0"}>Weekly</Button>
                                    </div>
                                    <p class="text-[10px] text-text-secondary italic leading-relaxed opacity-60">Determines when the system will automatically begin data duplication.</p>
                                </div>
                            </div>
                        </Card>
                    </div>

                {:else if activeTab === 'alerts'}
                    <div class="animate-in slide-in-from-bottom-4 duration-500">
                        <Card class="p-8 shadow-xl border-border-color/60 bg-bg-secondary">
                            <div class="flex items-center justify-between mb-8">
                                <div class="flex items-center gap-4">
                                    <div class="p-3 bg-action-color/10 rounded-xl text-action-color border border-action-color/20"><Bell size={24} /></div>
                                    <div>
                                        <h3 class="text-xl font-black text-text-primary uppercase tracking-tight">Alerting</h3>
                                        <p class="text-[11px] text-text-secondary font-medium uppercase tracking-wider opacity-60">Autonomous alerts via Apprise integration.</p>
                                    </div>
                                </div>
                                <Button variant="outline" size="sm" class="h-9 text-[10px] font-black uppercase tracking-widest border-action-color/30 text-action-color" onclick={addNotificationUrl}><Plus size={14} class="mr-1" /> Add Alert</Button>
                            </div>
                            <div class="space-y-4">
                                {#each notificationUrls as url, i}
                                    <div class="flex gap-3 group animate-in slide-in-from-right-2 duration-300">
                                        <Input bind:value={notificationUrls[i]} placeholder="discord://token/id" class="h-12 bg-bg-primary/50 border-border-color font-mono text-[11px] focus:border-action-color/50" />
                                        <Button variant="outline" size="icon" class="h-12 w-12 border-action-color/20 text-action-color hover:bg-action-color/10" onclick={() => handleTestNotification(notificationUrls[i], i)} disabled={testingUrlIdx !== null}>
                                            {#if testingUrlIdx === i} <RotateCw size={16} class="animate-spin" /> {:else} <Send size={16} /> {/if}
                                        </Button>
                                        <Button variant="ghost" size="icon" class="h-12 w-12 hover:bg-error-color/10 hover:text-error-color" onclick={() => removeNotificationUrl(i)}><Trash2 size={18} /></Button>
                                    </div>
                                {:else}
                                    <div class="py-20 border-2 border-dashed border-border-color rounded-2xl flex flex-col items-center justify-center opacity-20">
                                        <Bell size={64} class="mb-4" />
                                        <p class="text-xs font-black uppercase tracking-widest">No Alerts Configured</p>
                                    </div>
                                {/each}
                            </div>
                            <p class="text-[10px] text-text-secondary mt-8 leading-relaxed opacity-60 italic">Supports Discord, Slack, Email, and 80+ services. Format: <code>service://api_key</code></p>
                        </Card>
                    </div>

                {:else if activeTab === 'export'}
                    <div class="animate-in slide-in-from-bottom-4 duration-500">
                        <Card class="p-8 shadow-xl border-border-color/60 bg-bg-secondary">
                            <div class="flex items-center gap-4 mb-10">
                                <div class="p-3 bg-purple-500/10 rounded-xl text-purple-500 border border-purple-500/20"><Database size={24} /></div>
                                <div>
                                    <h3 class="text-xl font-black text-text-primary uppercase tracking-tight">System Export</h3>
                                    <p class="text-[11px] text-text-secondary font-medium uppercase tracking-wider opacity-60">Disaster recovery & state portability.</p>
                                </div>
                            </div>
                            <div class="grid grid-cols-1 md:grid-cols-2 gap-8">
                                <div class="p-8 bg-bg-primary/30 border border-border-color rounded-2xl flex flex-col gap-6">
                                    <div>
                                        <h4 class="text-sm font-black uppercase text-text-primary tracking-tight">Export Index</h4>
                                        <p class="text-[11px] text-text-secondary mt-2 leading-relaxed">Download a portable copy of the TapeHoard SQLite index. Essential for migration or cold storage.</p>
                                    </div>
                                    <Button variant="secondary" class="mt-auto h-12 font-black uppercase tracking-widest text-[11px] border border-white/5" onclick={handleBackup} disabled={exporting}>
                                        {#if exporting} <RotateCw size={18} class="mr-2 animate-spin" /> Preparing... {:else} <Download size={18} class="mr-2" /> Export Index (.db) {/if}
                                    </Button>
                                </div>
                                <div class="p-8 bg-bg-primary/30 border border-border-color rounded-2xl flex flex-col gap-6">
                                    <div>
                                        <h4 class="text-sm font-black uppercase text-text-primary tracking-tight">Import State</h4>
                                        <p class="text-[11px] text-text-secondary mt-2 leading-relaxed">Restore the entire system state. <span class="text-error-color font-bold">Warning: Overwrites all current data.</span></p>
                                    </div>
                                    <div class="relative mt-auto">
                                        <input type="file" accept=".db" class="hidden" id="db-import" onchange={handleRestore} disabled={importing} />
                                        <Button variant="outline" class="w-full h-12 font-black uppercase tracking-widest text-[11px] border-purple-500/30 text-purple-400 hover:bg-purple-500/10" onclick={() => document.getElementById('db-import')?.click()} disabled={importing}>
                                            {#if importing} <RotateCw size={18} class="mr-2 animate-spin" /> Rebuilding State... {:else} <Upload size={18} class="mr-2" /> Import State {/if}
                                        </Button>
                                    </div>
                                </div>
                            </div>
                        </Card>
                    </div>
                {/if}
            </div>
        </div>
    {/if}
</div>

<style>
    textarea::-webkit-scrollbar { width: 8px; }
    textarea::-webkit-scrollbar-track { background: transparent; }
    textarea::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.05); border-radius: 10px; }
</style>
