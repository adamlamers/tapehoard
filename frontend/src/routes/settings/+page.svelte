<script lang="ts">
    import { onMount } from 'svelte';
    import { Search, Save, ShieldAlert, FolderSearch, RotateCw, Plus, Trash2, Download, Database, Upload, CalendarClock, Zap, Bell, Send } from 'lucide-svelte';
    import { Button } from '$lib/components/ui/button';
    import { Card } from '$lib/components/ui/card';
    import { Input } from '$lib/components/ui/input';
    import {
        getSettingsSystemSettingsGet,
        updateSettingSystemSettingsPost,
        exportDatabaseSystemDatabaseExportGet,
        importDatabaseSystemDatabaseImportPost,
        testNotificationSystemNotificationsTestPost
    } from '$lib/api';
    import { toast } from "svelte-sonner";

    let sourceRoots = $state<string[]>(["/source_data"]);
    let restoreDestinations = $state<string[]>(["/restores"]);
    let globalExclusions = $state("*.tmp\nnode_modules/\n.DS_Store\nThumbs.db\nCache/\n");
    let scanSchedule = $state("");
    let archivalSchedule = $state("");
    let notificationUrls = $state<string[]>([]);

    let loading = $state(true);
    let saving = $state(false);
    let exporting = $state(false);
    let importing = $state(false);
    let testingUrlIdx = $state<number | null>(null);

    async function loadSettings() {
        loading = true;
        try {
            const response = await getSettingsSystemSettingsGet();
            if (response.data) {
                const data = response.data;
                if (data.source_roots) sourceRoots = JSON.parse(data.source_roots);
                if (data.restore_destinations) restoreDestinations = JSON.parse(data.restore_destinations);
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
                updateSettingSystemSettingsPost({ body: { key: "source_roots", value: JSON.stringify(sourceRoots) } }),
                updateSettingSystemSettingsPost({ body: { key: "restore_destinations", value: JSON.stringify(restoreDestinations) } }),
                updateSettingSystemSettingsPost({ body: { key: "global_exclusions", value: globalExclusions } }),
                updateSettingSystemSettingsPost({ body: { key: "schedule_scan", value: scanSchedule } }),
                updateSettingSystemSettingsPost({ body: { key: "schedule_archival", value: archivalSchedule } }),
                updateSettingSystemSettingsPost({ body: { key: "notification_urls", value: JSON.stringify(notificationUrls) } })
            ]);
            toast.success("Settings saved successfully");
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
            await testNotificationSystemNotificationsTestPost({
                body: { url }
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
            const url = "http://localhost:8000/system/database/export";
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
            await importDatabaseSystemDatabaseImportPost({
                body: {
                    file: file
                }
            });
            toast.success("Database restored successfully");
            setTimeout(() => window.location.reload(), 1500);
        } catch (error: any) {
            toast.error(error.body?.detail || "Failed to restore database");
        } finally {
            importing = false;
            input.value = "";
        }
    }

    function addRoot() {
        sourceRoots = [...sourceRoots, ""];
    }

    function removeRoot(index: number) {
        sourceRoots = sourceRoots.filter((_, i) => i !== index);
    }

    function addDest() {
        restoreDestinations = [...restoreDestinations, ""];
    }

    function removeDest(index: number) {
        restoreDestinations = restoreDestinations.filter((_, i) => i !== index);
    }

    function addNotificationUrl() {
        notificationUrls = [...notificationUrls, ""];
    }

    function removeNotificationUrl(index: number) {
        notificationUrls = notificationUrls.filter((_, i) => i !== index);
    }

    onMount(loadSettings);
</script>

<svelte:head>
    <title>System Settings - TapeHoard</title>
</svelte:head>

<div class="flex flex-col gap-8 h-full overflow-y-auto pr-2 pb-12 animate-in fade-in duration-700">
    <!-- Header -->
    <header class="flex justify-between items-center bg-bg-secondary px-8 py-5 rounded-xl border border-border-color shadow-2xl relative overflow-hidden shrink-0">
        <div class="absolute inset-0 bg-gradient-to-r from-orange-500/5 to-transparent pointer-events-none"></div>
        <div class="relative z-10">
            <h1 class="text-2xl font-black uppercase tracking-tighter text-text-primary flex items-center gap-3">
                <Search class="text-orange-500" size={28} />
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
            <span class="text-xs font-black uppercase tracking-widest">Parsing Manifests...</span>
        </div>
    {:else}
        <div class="grid grid-cols-1 xl:grid-cols-2 gap-8">
            <!-- Source Roots -->
            <Card class="p-8 shadow-xl border-border-color/60 bg-gradient-to-br from-bg-secondary to-bg-tertiary">
                <div class="flex items-center justify-between mb-6">
                    <div class="flex items-center gap-3">
                        <div class="p-2 bg-orange-500/10 rounded-lg text-orange-500 border border-orange-500/20"><Search size={24} /></div>
                        <div><h3 class="text-lg font-black text-text-primary uppercase tracking-tight">Source Roots</h3><p class="text-[11px] text-text-secondary font-medium uppercase tracking-wider opacity-60">Base directories to scan for backups.</p></div>
                    </div>
                    <Button variant="outline" size="sm" class="h-8 text-[10px] font-black uppercase tracking-widest border-orange-500/30 text-orange-400" onclick={addRoot}><Plus size={14} class="mr-1" /> Add Root</Button>
                </div>
                <div class="space-y-3">
                    {#each sourceRoots as root, i}
                        <div class="flex gap-2 animate-in slide-in-from-left-2 duration-300">
                            <Input bind:value={sourceRoots[i]} placeholder="/mnt/data" class="h-12 bg-bg-primary/50 border-border-color font-mono text-sm" />
                            <Button variant="ghost" size="icon" class="h-12 w-12 hover:bg-error-color/10 hover:text-error-color" onclick={() => removeRoot(i)}><Trash2 size={18} /></Button>
                        </div>
                    {/each}
                </div>
            </Card>

            <!-- Restore Destinations -->
            <Card class="p-8 shadow-xl border-border-color/60 bg-gradient-to-br from-bg-secondary to-bg-tertiary">
                <div class="flex items-center justify-between mb-6">
                    <div class="flex items-center gap-3">
                        <div class="p-2 bg-success-color/10 rounded-lg text-success-color border border-success-color/20"><Download size={24} /></div>
                        <div><h3 class="text-lg font-black text-text-primary uppercase tracking-tight">Recovery Targets</h3><p class="text-[11px] text-text-secondary font-medium uppercase tracking-wider opacity-60">Locations available for file recovery.</p></div>
                    </div>
                    <Button variant="outline" size="sm" class="h-8 text-[10px] font-black uppercase tracking-widest border-success-color/30 text-success-color" onclick={addDest}><Plus size={14} class="mr-1" /> Add Target</Button>
                </div>
                <div class="space-y-3">
                    {#each restoreDestinations as dest, i}
                        <div class="flex gap-2 animate-in slide-in-from-right-2 duration-300">
                            <Input bind:value={restoreDestinations[i]} placeholder="/mnt/recovery" class="h-12 bg-bg-primary/50 border-border-color font-mono text-sm" />
                            <Button variant="ghost" size="icon" class="h-12 w-12 hover:bg-error-color/10 hover:text-error-color" onclick={() => removeDest(i)}><Trash2 size={18} /></Button>
                        </div>
                    {/each}
                </div>
            </Card>
        </div>

        <!-- Global Exclusions -->
        <Card class="p-8 shadow-xl border-border-color/60 bg-gradient-to-br from-bg-secondary to-bg-tertiary">
            <div class="flex items-center justify-between mb-6">
                <div class="flex items-center gap-3">
                    <div class="p-2 bg-orange-500/10 rounded-lg text-orange-500 border border-orange-500/20"><FolderSearch size={24} /></div>
                    <div><h3 class="text-lg font-black text-text-primary uppercase tracking-tight">Global Exclusions</h3><p class="text-[11px] text-text-secondary font-medium uppercase tracking-wider opacity-60">Git-style ignore patterns for all scans.</p></div>
                </div>
            </div>
            <div class="space-y-4">
                <p class="text-[11px] text-text-secondary uppercase tracking-widest font-black opacity-40 mb-2">Exclusion Rules (One per line)</p>
                <textarea
                    bind:value={globalExclusions}
                    class="w-full h-48 bg-bg-primary/50 border border-border-color rounded-xl p-4 font-mono text-sm text-text-primary focus:ring-2 focus:ring-orange-500/20 focus:border-orange-500/40 transition-all outline-none"
                    placeholder="*.tmp&#10;node_modules/&#10;.DS_Store"
                ></textarea>
            </div>
            <div class="mt-6 p-4 bg-orange-500/5 border border-dashed border-orange-500/30 rounded-lg flex gap-4 items-start">
                <ShieldAlert size={20} class="text-orange-500 shrink-0 mt-0.5" />
                <p class="text-[12px] text-text-secondary leading-normal font-medium"><strong class="text-orange-500 uppercase tracking-tight text-[11px] block mb-1">Warning</strong>Broad exclusion patterns can result in incomplete backups.</p>
            </div>
        </Card>

        <div class="grid grid-cols-1 xl:grid-cols-2 gap-8">
            <!-- Automated Scheduling -->
            <Card class="p-8 shadow-xl border-border-color/60 bg-gradient-to-br from-bg-secondary to-bg-tertiary">
                <div class="flex items-center justify-between mb-6">
                    <div class="flex items-center gap-3">
                        <div class="p-2 bg-blue-500/10 rounded-lg text-blue-500 border border-blue-500/20"><CalendarClock size={24} /></div>
                        <div><h3 class="text-lg font-black text-text-primary uppercase tracking-tight">Automated Scheduling</h3><p class="text-[11px] text-text-secondary font-medium uppercase tracking-wider opacity-60">Manage recurring background tasks.</p></div>
                    </div>
                </div>
                <div class="space-y-6">
                    <div class="space-y-4">
                        <div class="flex items-center gap-2 mb-2">
                            <Zap size={14} class="text-blue-400" />
                            <span class="text-[11px] font-black uppercase tracking-widest text-text-primary">System Scan Frequency</span>
                        </div>
                        <div class="flex gap-2">
                            <Input
                                bind:value={scanSchedule}
                                placeholder="0 2 * * *"
                                class="h-11 bg-bg-primary/50 border-border-color font-mono text-sm"
                            />
                            <Button variant="outline" class="h-11 px-4 text-[10px] uppercase font-black tracking-widest shrink-0" onclick={() => scanSchedule = "0 2 * * *"}>Daily</Button>
                        </div>
                        <p class="text-[10px] text-text-secondary italic leading-relaxed opacity-60">Standard Cron expression (m h d M dw). Empty to disable.</p>
                    </div>

                    <div class="space-y-4">
                        <div class="flex items-center gap-2 mb-2">
                            <Zap size={14} class="text-success-color" />
                            <span class="text-[11px] font-black uppercase tracking-widest text-text-primary">Media Archival Frequency</span>
                        </div>
                        <div class="flex gap-2">
                            <Input
                                bind:value={archivalSchedule}
                                placeholder="0 4 * * 0"
                                class="h-11 bg-bg-primary/50 border-border-color font-mono text-sm"
                            />
                            <Button variant="outline" class="h-11 px-4 text-[10px] uppercase font-black tracking-widest shrink-0" onclick={() => archivalSchedule = "0 4 * * 0"}>Weekly</Button>
                        </div>
                        <p class="text-[10px] text-text-secondary italic leading-relaxed opacity-60">Standard Cron expression. Weekly default is Sunday at 4 AM.</p>
                    </div>
                </div>
            </Card>

            <!-- Notifications -->
            <Card class="p-8 shadow-xl border-border-color/60 bg-gradient-to-br from-bg-secondary to-bg-tertiary">
                <div class="flex items-center justify-between mb-6">
                    <div class="flex items-center gap-3">
                        <div class="p-2 bg-action-color/10 rounded-lg text-action-color border border-action-color/20"><Bell size={24} /></div>
                        <div><h3 class="text-lg font-black text-text-primary uppercase tracking-tight">Notification Fleet</h3><p class="text-[11px] text-text-secondary font-medium uppercase tracking-wider opacity-60">External alerts via Apprise URLs.</p></div>
                    </div>
                    <Button variant="outline" size="sm" class="h-8 text-[10px] font-black uppercase tracking-widest border-action-color/30 text-action-color" onclick={addNotificationUrl}><Plus size={14} class="mr-1" /> Add Service</Button>
                </div>
                <div class="space-y-4">
                    {#each notificationUrls as url, i}
                        <div class="flex gap-2 animate-in slide-in-from-right-2 duration-300">
                            <Input bind:value={notificationUrls[i]} placeholder="discord://token/id" class="h-12 bg-bg-primary/50 border-border-color font-mono text-[11px]" />
                            <Button
                                variant="outline"
                                size="icon"
                                class="h-12 w-12 border-action-color/20 text-action-color hover:bg-action-color/10"
                                onclick={() => handleTestNotification(notificationUrls[i], i)}
                                disabled={testingUrlIdx !== null}
                            >
                                {#if testingUrlIdx === i}
                                    <RotateCw size={16} class="animate-spin" />
                                {:else}
                                    <Send size={16} />
                                {/if}
                            </Button>
                            <Button variant="ghost" size="icon" class="h-12 w-12 hover:bg-error-color/10 hover:text-error-color" onclick={() => removeNotificationUrl(i)}><Trash2 size={18} /></Button>
                        </div>
                    {/each}
                    {#if notificationUrls.length === 0}
                        <div class="py-12 border-2 border-dashed border-border-color rounded-xl flex flex-col items-center justify-center opacity-20">
                            <Bell size={48} class="mb-2" />
                            <p class="text-[10px] font-black uppercase tracking-widest">No Alerts Configured</p>
                        </div>
                    {/if}
                </div>
                <p class="text-[10px] text-text-secondary mt-6 leading-relaxed opacity-60 italic">Supports Discord, Slack, Telegram, Email, and more via Apprise. Format: <code>discord://webhook_id/webhook_token</code></p>
            </Card>
        </div>

        <!-- Database Maintenance -->
        <Card class="p-8 shadow-xl border-border-color/60 bg-gradient-to-br from-bg-secondary to-bg-tertiary">
            <div class="flex items-center justify-between mb-6">
                <div class="flex items-center gap-3">
                    <div class="p-2 bg-purple-500/10 rounded-lg text-purple-500 border border-purple-500/20"><Database size={24} /></div>
                    <div><h3 class="text-lg font-black text-text-primary uppercase tracking-tight">Database Maintenance</h3><p class="text-[11px] text-text-secondary font-medium uppercase tracking-wider opacity-60">Disaster recovery & index portability.</p></div>
                </div>
            </div>
            <div class="grid grid-cols-2 gap-4">
                <div class="p-6 bg-bg-primary/30 border border-border-color rounded-xl flex flex-col gap-4">
                    <div>
                        <h4 class="text-sm font-black uppercase text-text-primary tracking-tight">Export Index</h4>
                        <p class="text-[11px] text-text-secondary mt-1 leading-relaxed">Download a portable copy of the TapeHoard index database. This includes all file tracking data, media history, and system settings.</p>
                    </div>
                    <Button variant="secondary" class="mt-auto h-11 font-black uppercase tracking-widest text-[10px]" onclick={handleBackup} disabled={exporting}>
                        {#if exporting}
                            <RotateCw size={16} class="mr-2 animate-spin" /> Preparing...
                        {:else}
                            <Download size={16} class="mr-2" /> Export Database (.db)
                        {/if}
                    </Button>
                </div>
                <div class="p-6 bg-bg-primary/30 border border-border-color rounded-xl flex flex-col gap-4">
                    <div>
                        <h4 class="text-sm font-black uppercase text-text-primary tracking-tight">Import Index</h4>
                        <p class="text-[11px] text-text-secondary mt-1 leading-relaxed">Restore the system state from a previous database export. <span class="text-error-color font-bold italic">Warning: This will overwrite all current data!</span></p>
                    </div>
                    <div class="relative">
                        <input type="file" accept=".db" class="hidden" id="db-import" onchange={handleRestore} disabled={importing} />
                        <Button variant="outline" class="w-full h-11 font-black uppercase tracking-widest text-[10px] border-purple-500/30 text-purple-400 hover:bg-purple-500/10" onclick={() => document.getElementById('db-import')?.click()} disabled={importing}>
                            {#if importing}
                                <RotateCw size={16} class="mr-2 animate-spin" /> Restoring...
                            {:else}
                                <Upload size={16} class="mr-2" /> Import & Restore
                            {/if}
                        </Button>
                    </div>
                </div>
            </div>
        </Card>
    {/if}
</div>
