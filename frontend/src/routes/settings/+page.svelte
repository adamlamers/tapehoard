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
        ShieldCheck,
        FolderSearch,
        Download,
        Upload,
        Terminal,
        Globe,
        Key,
        ChevronDown
    } from "lucide-svelte";
    import { Button } from "$lib/components/ui/button";
    import PageHeader from "$lib/components/ui/PageHeader.svelte";
    import SectionHeader from "$lib/components/ui/SectionHeader.svelte";
    import { Card } from "$lib/components/ui/card";
    import { Input } from "$lib/components/ui/input";
    import {
        getSettings,
        updateSettings,
        testNotification,
        exportDatabase,
        importDatabase,
        testExclusions,
        downloadExclusionReport,
        listSecrets,
        createSecret,
        deleteSecret
    } from "$lib/api";
    import { toast } from "svelte-sonner";
    import { cn, formatSize } from "$lib/utils";
    import { beforeNavigate } from '$app/navigation';
    import type { Navigation } from '@sveltejs/kit';
    import { showSupportButton } from "$lib/stores/ui";

    let sourceRoots = $state<string[]>(["/source_data"]);
    let restoreDestinations = $state<string[]>(["/restores"]);
    let tapeDrives = $state<string[]>(["/dev/nst0"]);
    let globalExclusions = $state("");
    let scanSchedule = $state("");
    let archivalSchedule = $state("");
    let notificationUrls = $state<string[]>([]);
    let ioniceLevel = $state("idle");
    let tapeWriteStrategy = $state("stage");
    let redundancyTarget = $state(1);

    // Secrets keystore
    let secretsList = $state<string[]>([]);
    let newSecretName = $state("");
    let newSecretValue = $state("");
    let showAddSecret = $state(false);

    let initialState = $state("");
    const isDirty = $derived(initialState !== JSON.stringify({
        sourceRoots,
        restoreDestinations,
        tapeDrives,
        globalExclusions,
        scanSchedule,
        archivalSchedule,
        notificationUrls,
        ioniceLevel,
        tapeWriteStrategy,
        redundancyTarget
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
    let testingExclusions = $state(false);
    let exclusionResults = $state<{
        total_files: number;
        total_size: number;
        matched_count: number;
        matched_size: number;
        sample: Array<{
            name: string;
            path: string;
            type: string;
            size: number;
            mtime: number;
            ignored: boolean;
            sha256_hash: string | null;
        }>;
    } | null>(null);

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
        { id: "secrets", label: "Secrets", icon: Key },
        { id: "notifications", label: "Alerting", icon: Bell },
        { id: "system", label: "System", icon: Cpu },
    ];

    async function loadSettings() {
        loading = true;
        try {
            const response = await getSettings();
            if (response.data) {
                const data = response.data as Record<string, string>;
                if (data.source_roots) sourceRoots = JSON.parse(data.source_roots);
                if (data.restore_destinations) restoreDestinations = JSON.parse(data.restore_destinations);
                if (data.tape_drives) tapeDrives = JSON.parse(data.tape_drives);
                if (data.global_exclusions) globalExclusions = data.global_exclusions;
                if (data.schedule_scan) scanSchedule = data.schedule_scan;
                if (data.schedule_archival) archivalSchedule = data.schedule_archival;
                if (data.notification_urls) notificationUrls = JSON.parse(data.notification_urls);
                if (data.ionice_level) ioniceLevel = data.ionice_level;
                if (data.tape_write_strategy) tapeWriteStrategy = data.tape_write_strategy;
                if (data.redundancy_target) redundancyTarget = parseInt(data.redundancy_target, 10) || 1;
            }

            // Load secrets
            const secretsRes = await listSecrets();
            if (secretsRes.data) secretsList = secretsRes.data as string[];

            // Capture snapshot for dirty check
            initialState = JSON.stringify({
                sourceRoots,
                restoreDestinations,
                tapeDrives,
                globalExclusions,
                scanSchedule,
                archivalSchedule,
                notificationUrls,
                ioniceLevel,
                tapeWriteStrategy,
                redundancyTarget
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
                updateSettings({ body: { key: "source_roots", value: JSON.stringify(sourceRoots) } }),
                updateSettings({ body: { key: "restore_destinations", value: JSON.stringify(restoreDestinations) } }),
                updateSettings({ body: { key: "tape_drives", value: JSON.stringify(tapeDrives) } }),
                updateSettings({ body: { key: "global_exclusions", value: globalExclusions } }),
                updateSettings({ body: { key: "schedule_scan", value: scanSchedule } }),
                updateSettings({ body: { key: "schedule_archival", value: archivalSchedule } }),
                updateSettings({ body: { key: "notification_urls", value: JSON.stringify(notificationUrls) } }),
                updateSettings({ body: { key: "ionice_level", value: ioniceLevel } }),
                updateSettings({ body: { key: "tape_write_strategy", value: tapeWriteStrategy } }),
                updateSettings({ body: { key: "redundancy_target", value: String(redundancyTarget) } })
            ]);

            // Snapshot saved state
            initialState = JSON.stringify({
                sourceRoots,
                restoreDestinations,
                tapeDrives,
                globalExclusions,
                scanSchedule,
                archivalSchedule,
                notificationUrls,
                ioniceLevel,
                tapeWriteStrategy,
                redundancyTarget
            });

            toast.success("System configuration committed");
        } catch (error) {
            toast.error("Failed to save settings");
        } finally {
            saving = false;
        }
    }

    async function handleAddSecret() {
        if (!newSecretName.trim() || !newSecretValue.trim()) {
            toast.error("Secret name and value are required");
            return;
        }
        try {
            await createSecret({ body: { name: newSecretName.trim(), value: newSecretValue.trim() } });
            toast.success(`Secret '${newSecretName}' saved`);
            secretsList = [...secretsList, newSecretName.trim()];
            newSecretName = "";
            newSecretValue = "";
            showAddSecret = false;
        } catch (error) {
            toast.error("Failed to save secret");
        }
    }

    async function handleDeleteSecret(name: string) {
        if (!confirm(`Delete secret '${name}'? This may break media that references it.`)) return;
        try {
            await deleteSecret({ body: { name } });
            toast.success(`Secret '${name}' deleted`);
            secretsList = secretsList.filter(s => s !== name);
        } catch (error) {
            toast.error("Failed to delete secret");
        }
    }

    async function handleExport() {
        exporting = true;
        try {
            const response = await exportDatabase();
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
            await testNotification({ body: { url } });
            toast.success("Test notification dispatched");
        } catch (error) {
            toast.error("Notification test failed");
        }
    }

    async function handleTestExclusions() {
        testingExclusions = true;
        exclusionResults = null;
        try {
            const response = await testExclusions({
                body: { patterns: globalExclusions, limit: 10 }
            });
            if (response.data) {
                exclusionResults = response.data as any;
            }
        } catch (error: any) {
            toast.error(error.body?.detail || "Failed to test exclusions");
        } finally {
            testingExclusions = false;
        }
    }

    async function handleDownloadExclusionReport() {
        try {
            const response = await downloadExclusionReport({
                body: { patterns: globalExclusions, limit: 10 }
            });
            if (response.data) {
                const blob = await (response.data as any).blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `exclusion_report_${new Date().toISOString().split('T')[0]}.csv`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                toast.success("Exclusion report downloaded");
            }
        } catch (error) {
            toast.error("Download failed");
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

<div class="flex flex-col h-full gap-6 animate-in fade-in duration-700">
    <PageHeader
        title="Station settings"
        description="Configure archival logic & hardware"
        icon={Database}
    >
        {#snippet actions()}
            <Button variant="default" class="px-6 shadow-lg shadow-blue-500/10" onclick={saveSettings} disabled={saving || !isDirty}>
                {#if saving}
                    <RotateCw size={14} class="mr-2 animate-spin" /> Saving...
                {:else}
                    <Save size={14} class="mr-2" /> Save configuration
                {/if}
            </Button>
        {/snippet}
    </PageHeader>

    <div class="flex flex-col lg:flex-row gap-6 flex-1 overflow-hidden min-h-0">
        <!-- Sidebar Navigation -->
        <nav class="w-full lg:w-56 flex lg:flex-col gap-1 shrink-0 overflow-x-auto lg:overflow-x-visible pb-2 lg:pb-0">
            {#each tabs as tab}
                <button
                    class={cn(
                        "flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-all whitespace-nowrap cursor-pointer",
                        activeTab === tab.id
                            ? "bg-blue-500/10 text-blue-500 border border-blue-500/20 shadow-[0_0_15px_rgba(59,130,246,0.1)]"
                            : "text-text-secondary hover:bg-white/5 border border-transparent"
                    )}
                    onclick={() => activeTab = tab.id}
                >
                    <tab.icon size={16} />
                    {tab.label}
                </button>
            {/each}
        </nav>

        <!-- Tab Content -->
        <main class="flex-1 overflow-y-auto pr-2 pb-8">
            {#if loading}
                <div class="h-80 bg-bg-secondary animate-pulse rounded-xl border border-border-color/50"></div>
            {:else}
                {#if activeTab === 'hardware'}
                    <div class="animate-in slide-in-from-bottom-4 duration-500">
                        <Card class="p-5 shadow-xl">
                            <SectionHeader title="LTO hardware" icon={Monitor} class="mb-6 px-0" />
                            <div class="space-y-3">
                                {#each tapeDrives as drive, i}
                                    <div class="flex gap-2 animate-in slide-in-from-left-4 duration-300" style="animation-delay: {i * 50}ms">
                                        <div class="relative flex-1">
                                            <Terminal size={14} class="absolute left-4 top-3 text-text-secondary opacity-50" />
                                            <Input bind:value={tapeDrives[i]} placeholder="/dev/nst0" class="h-10 bg-bg-primary/50 pl-10 border-border-color font-mono text-xs" />
                                        </div>
                                        <Button variant="ghost" class="h-10 w-10 shrink-0 rounded-xl bg-error-color/5 text-error-color/60 hover:bg-error-color/10 hover:text-error-color" onclick={() => removeDrive(i)}><Trash2 size={18} /></Button>
                                    </div>
                                {/each}
                                <Button variant="outline" class="w-full h-11 border-dashed border-2 font-medium text-sm mt-2" onclick={addDrive}>
                                    <Plus size={20} class="mr-2" /> Add tape drive
                                </Button>
                            </div>
                        </Card>
                    </div>

                {:else if activeTab === 'paths'}
                    <div class="animate-in slide-in-from-bottom-4 duration-500 space-y-6">
                        <Card class="p-5 shadow-xl">
                            <SectionHeader title="Source roots" icon={HardDrive} class="mb-6 px-0" />
                            <div class="space-y-3">
                                {#each sourceRoots as root, i}
                                    <div class="flex gap-2">
                                        <Input bind:value={sourceRoots[i]} placeholder="/mnt/data" class="h-10 bg-bg-primary/50 border-border-color font-mono text-xs" />
                                        <Button variant="ghost" class="h-10 w-10 shrink-0 rounded-xl bg-error-color/5 text-error-color/60 hover:bg-error-color/10 hover:text-error-color" onclick={() => removeSource(i)}><Trash2 size={18} /></Button>
                                    </div>
                                {/each}
                                <Button variant="outline" class="w-full h-11 border-dashed border-2 font-medium text-sm" onclick={addSource}><Plus size={20} class="mr-2" /> Add source root</Button>
                            </div>
                        </Card>

                        <Card class="p-5 shadow-xl">
                            <SectionHeader title="Restore targets" icon={ArrowRight} iconColor="text-success-color" class="mb-6 px-0" />
                            <div class="space-y-3">
                                {#each restoreDestinations as dest, i}
                                    <div class="flex gap-2">
                                        <Input bind:value={restoreDestinations[i]} placeholder="/restores" class="h-10 bg-bg-primary/50 border-border-color font-mono text-xs" />
                                        <Button variant="ghost" class="h-10 w-10 shrink-0 rounded-xl bg-error-color/5 text-error-color/60 hover:bg-error-color/10 hover:text-error-color" onclick={() => removeDest(i)}><Trash2 size={18} /></Button>
                                    </div>
                                {/each}
                                <Button variant="outline" class="w-full h-11 border-dashed border-2 font-medium text-sm" onclick={addDest}><Plus size={20} class="mr-2" /> Add restore path</Button>
                            </div>
                        </Card>
                    </div>

                {:else if activeTab === 'exclusions'}
                    <div class="animate-in slide-in-from-bottom-4 duration-500 space-y-6">
                        <Card class="p-5 shadow-xl">
                            <SectionHeader title="Exclusion policy" icon={ListX} iconColor="text-orange-500" class="mb-6 px-0" />
                            <div class="space-y-5">
                                <textarea
                                    bind:value={globalExclusions}
                                    class="w-full h-56 bg-bg-primary/50 border border-border-color rounded-2xl p-5 font-mono text-xs text-text-primary focus:ring-2 focus:ring-orange-500/20 focus:border-orange-500/40 transition-all outline-none resize-none"
                                    placeholder="Add one pattern per line (e.g. .git/)"
                                ></textarea>

                                <div class="space-y-3">
                                    <h4 class="text-[10px] font-semibold uppercase tracking-wider text-text-secondary opacity-40">Common patterns</h4>
                                    <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
                                        {#each commonExclusions as item}
                                            <button
                                                class="flex items-center justify-between px-3 py-1.5 bg-bg-primary/40 border border-border-color/60 rounded-lg hover:border-orange-500/40 hover:bg-orange-500/5 transition-all group"
                                                onclick={() => addCommonExclusion(item.pattern)}
                                            >
                                                <span class="text-[10px] font-medium text-text-secondary group-hover:text-text-primary">{item.label}</span>
                                                <Plus size={10} class="text-text-secondary opacity-20 group-hover:opacity-100" />
                                            </button>
                                        {/each}
                                    </div>
                                </div>

                                <div class="flex gap-3">
                                    <Button
                                        variant="outline"
                                        class="h-10 px-4 text-sm font-medium border-orange-500/30 text-orange-500 hover:bg-orange-500/5"
                                        onclick={handleTestExclusions}
                                        disabled={testingExclusions || !globalExclusions.trim()}
                                    >
                                        {#if testingExclusions}
                                            <RotateCw size={14} class="mr-2 animate-spin" /> Testing...
                                        {:else}
                                            <FolderSearch size={14} class="mr-2" /> Test exception list
                                        {/if}
                                    </Button>
                                    {#if exclusionResults && exclusionResults.matched_count > 0}
                                        <Button
                                            variant="outline"
                                            class="h-10 px-4 text-sm font-medium border-border-color hover:border-blue-500/40 hover:bg-blue-500/5"
                                            onclick={handleDownloadExclusionReport}
                                        >
                                            <Download size={14} class="mr-2" /> Download CSV report
                                        </Button>
                                    {/if}
                                </div>

                                {#if exclusionResults}
                                    <div class="space-y-4">
                                        <div class="grid grid-cols-3 gap-4">
                                            <div class="bg-bg-primary/50 rounded-xl p-4 border border-border-color/60">
                                                <span class="text-[10px] font-medium text-text-secondary uppercase tracking-wide">Indexed files</span>
                                                <p class="text-2xl font-bold text-text-primary mono mt-1">{exclusionResults.total_files.toLocaleString()}</p>
                                                <p class="text-xs text-text-secondary mono mt-1">{formatSize(exclusionResults.total_size)}</p>
                                            </div>
                                            <div class="bg-orange-500/5 rounded-xl p-4 border border-orange-500/20">
                                                <span class="text-[10px] font-medium text-orange-500 uppercase tracking-wide">Would be excluded</span>
                                                <p class="text-2xl font-bold text-orange-500 mono mt-1">{exclusionResults.matched_count.toLocaleString()}</p>
                                                <p class="text-xs text-orange-500 mono mt-1">{formatSize(exclusionResults.matched_size)}</p>
                                            </div>
                                            <div class="bg-bg-primary/50 rounded-xl p-4 border border-border-color/60">
                                                <span class="text-[10px] font-medium text-text-secondary uppercase tracking-wide">Match rate</span>
                                                <p class="text-2xl font-bold text-text-primary mono mt-1">
                                                    {exclusionResults.total_files > 0
                                                        ? Math.round((exclusionResults.matched_count / exclusionResults.total_files) * 100)
                                                        : 0}%
                                                </p>
                                                <p class="text-xs text-text-secondary mono mt-1">
                                                    {exclusionResults.total_size > 0
                                                        ? Math.round((exclusionResults.matched_size / exclusionResults.total_size) * 100)
                                                        : 0}% by size
                                                </p>
                                            </div>
                                        </div>

                                        {#if exclusionResults.sample.length > 0}
                                            <div class="bg-bg-primary/30 rounded-xl border border-border-color/60 overflow-hidden">
                                                <div class="px-4 py-3 border-b border-border-color/60 bg-bg-primary/50">
                                                    <span class="text-xs font-semibold text-text-primary">Sample of matched files ({exclusionResults.sample.length} shown)</span>
                                                </div>
                                                <div class="overflow-x-auto">
                                                    <table class="w-full text-xs">
                                                        <thead>
                                                            <tr class="border-b border-border-color/40">
                                                                <th class="px-4 py-2 text-left text-text-secondary font-medium">Path</th>
                                                                <th class="px-4 py-2 text-right text-text-secondary font-medium w-24">Size</th>
                                                                <th class="px-4 py-2 text-right text-text-secondary font-medium w-20">Type</th>
                                                            </tr>
                                                        </thead>
                                                        <tbody>
                                                            {#each exclusionResults.sample as file}
                                                                <tr class="border-b border-border-color/20 last:border-0">
                                                                    <td class="px-4 py-2 text-text-primary font-mono truncate max-w-xs">{file.path}</td>
                                                                    <td class="px-4 py-2 text-right text-text-secondary mono">{file.size?.toLocaleString() || '—'}</td>
                                                                    <td class="px-4 py-2 text-right">
                                                                        <span class="inline-flex px-2 py-0.5 rounded text-[10px] font-medium {file.type === 'directory' ? 'bg-blue-500/10 text-blue-500' : 'bg-text-secondary/10 text-text-secondary'}">
                                                                            {file.type}
                                                                        </span>
                                                                    </td>
                                                                </tr>
                                                            {/each}
                                                        </tbody>
                                                    </table>
                                                </div>
                                            </div>
                                        {:else if exclusionResults.matched_count === 0}
                                            <div class="p-4 bg-green-500/5 border border-dashed border-green-500/30 rounded-xl flex gap-4 items-start">
                                                <ShieldCheck size={20} class="text-green-500 shrink-0 mt-0.5" />
                                                <div>
                                                    <span class="text-xs font-bold text-green-500 uppercase tracking-wider">No matches</span>
                                                    <p class="text-xs text-text-secondary leading-relaxed font-medium">None of the current indexed files match these exclusion patterns.</p>
                                                </div>
                                            </div>
                                        {/if}
                                    </div>
                                {/if}

                                <div class="p-4 bg-orange-500/5 border border-dashed border-orange-500/30 rounded-xl flex gap-4 items-start">
                                    <ShieldAlert size={20} class="text-orange-500 shrink-0 mt-0.5" />
                                    <div class="space-y-1">
                                        <span class="text-xs font-bold text-orange-500 uppercase tracking-wider">Policy warning</span>
                                        <p class="text-xs text-text-secondary leading-relaxed font-medium">Broad exclusion patterns can result in critical data being skipped during the archival process. Ensure patterns match only transient data.</p>
                                    </div>
                                </div>
                            </div>
                        </Card>
                    </div>

                {:else if activeTab === 'scheduling'}
                    <div class="animate-in slide-in-from-bottom-4 duration-500 space-y-6">
                        <Card class="p-5 shadow-xl">
                            <SectionHeader title="Scan frequency" icon={CalendarClock} class="mb-6 px-0" />
                            <div class="flex gap-3">
                                <div class="relative flex-1">
                                    <Terminal size={14} class="absolute left-4 top-3 text-text-secondary opacity-50" />
                                    <Input bind:value={scanSchedule} placeholder="0 2 * * *" class="h-10 bg-bg-primary/50 pl-10 border-border-color font-mono text-xs" />
                                </div>
                                <div class="flex gap-2">
                                    <Button variant="outline" class="h-10 px-3 text-[10px] font-semibold" onclick={() => scanSchedule = "0 * * * *"}>Hourly</Button>
                                    <Button variant="outline" class="h-10 px-3 text-[10px] font-semibold" onclick={() => scanSchedule = "0 2 * * *"}>Daily</Button>
                                </div>
                            </div>
                        </Card>

                        <Card class="p-5 shadow-xl">
                            <SectionHeader title="Archival frequency" icon={CalendarClock} iconColor="text-action-color" class="mb-6 px-0" />
                            <div class="flex gap-3">
                                <div class="relative flex-1">
                                    <Terminal size={14} class="absolute left-4 top-3 text-text-secondary opacity-50" />
                                    <Input bind:value={archivalSchedule} placeholder="0 4 * * 0" class="h-10 bg-bg-primary/50 pl-10 border-border-color font-mono text-xs" />
                                </div>
                                <div class="flex gap-2">
                                    <Button variant="outline" class="h-10 px-3 text-[10px] font-semibold" onclick={() => archivalSchedule = "0 4 * * 0"}>Weekly</Button>
                                    <Button variant="outline" class="h-10 px-3 text-[10px] font-semibold" onclick={() => archivalSchedule = "0 4 1 * *"}>Monthly</Button>
                                </div>
                            </div>
                        </Card>
                    </div>

                {:else if activeTab === 'notifications'}
                    <div class="animate-in slide-in-from-bottom-4 duration-500">
                        <Card class="p-5 shadow-xl">
                            <SectionHeader title="Alerting endpoints" icon={Bell} class="mb-6 px-0" />
                            <div class="space-y-3">
                                {#each notificationUrls as url, i}
                                    <div class="flex gap-2">
                                        <div class="relative flex-1">
                                            <Globe size={14} class="absolute left-4 top-3 text-text-secondary opacity-50" />
                                            <Input bind:value={notificationUrls[i]} placeholder="prowl://apikey" class="h-10 bg-bg-primary/50 pl-10 border-border-color font-mono text-xs" />
                                        </div>
                                        <Button variant="outline" class="h-10 px-3 text-[10px] font-semibold border-border-color" onclick={() => testNotify(notificationUrls[i])}>Test</Button>
                                        <Button variant="ghost" class="h-10 w-10 shrink-0 rounded-xl bg-error-color/5 text-error-color/60 hover:bg-error-color/10 hover:text-error-color" onclick={() => removeNotify(i)}><Trash2 size={18} /></Button>
                                    </div>
                                {/each}
                                <Button variant="outline" class="w-full h-11 border-dashed border-2 font-medium text-sm" onclick={addNotify}><Plus size={20} class="mr-2" /> Add notification endpoint</Button>
                            </div>
                        </Card>
                    </div>

                {:else if activeTab === 'secrets'}
                    <div class="animate-in slide-in-from-bottom-4 duration-500 space-y-6">
                        <Card class="p-5 shadow-xl">
                            <SectionHeader title="Secrets Keystore" icon={Key} class="mb-6 px-0" />
                            <p class="text-sm text-text-secondary opacity-60 mb-4">Store sensitive credentials centrally. Media configurations reference secrets by name instead of storing raw values.</p>

                            {#if secretsList.length > 0}
                                <div class="space-y-2 mb-4">
                                    {#each secretsList as secret}
                                        <div class="flex items-center justify-between p-3 bg-bg-primary/50 rounded-lg border border-border-color">
                                            <div class="flex items-center gap-3">
                                                <Key size={14} class="text-text-secondary opacity-40" />
                                                <span class="text-sm font-medium text-text-primary">{secret}</span>
                                            </div>
                                            <Button variant="ghost" size="icon" class="h-8 w-8 text-error-color/60 hover:text-error-color hover:bg-error-color/10" onclick={() => handleDeleteSecret(secret)}>
                                                <Trash2 size={14} />
                                            </Button>
                                        </div>
                                    {/each}
                                </div>
                            {:else}
                                <div class="text-center py-8 opacity-30 mb-4">
                                    <Key size={32} class="mx-auto mb-2" />
                                    <p class="text-sm">No secrets stored yet</p>
                                </div>
                            {/if}

                            {#if showAddSecret}
                                <div class="space-y-3 p-4 bg-bg-primary/30 rounded-lg border border-border-color">
                                    <div class="space-y-2">
                                        <label class="text-xs font-medium text-text-secondary ml-1" for="new-secret-name">Secret Name</label>
                                        <Input id="new-secret-name" bind:value={newSecretName} placeholder="e.g., aws-production-key" class="h-10 bg-bg-primary border-border-color text-sm" />
                                    </div>
                                    <div class="space-y-2">
                                        <label class="text-xs font-medium text-text-secondary ml-1" for="new-secret-value">Secret Value</label>
                                        <Input id="new-secret-value" bind:value={newSecretValue} type="password" placeholder="Enter secret value" class="h-10 bg-bg-primary border-border-color font-mono text-sm" />
                                    </div>
                                    <div class="flex gap-2">
                                        <Button variant="outline" class="flex-1 h-10" onclick={() => { showAddSecret = false; newSecretName = ''; newSecretValue = ''; }}>Cancel</Button>
                                        <Button variant="default" class="flex-[2] h-10" onclick={handleAddSecret}>Save Secret</Button>
                                    </div>
                                </div>
                            {:else}
                                <Button variant="outline" class="w-full h-11 border-dashed border-2 font-medium text-sm" onclick={() => showAddSecret = true}>
                                    <Plus size={20} class="mr-2" /> Add Secret
                                </Button>
                            {/if}
                        </Card>
                    </div>

                {:else if activeTab === 'system'}
                    <div class="animate-in slide-in-from-bottom-4 duration-500 space-y-6">
                        <Card class="p-5 shadow-xl">
                            <SectionHeader title="I/O scheduling" icon={Cpu} class="mb-6 px-0" />
                            <div class="space-y-4">
                                <div class="space-y-2">
                                    <label class="text-xs font-medium text-text-secondary ml-1" for="ionice-level">Background job I/O priority</label>
                                    <div class="relative">
                                        <select id="ionice-level" bind:value={ioniceLevel} class="w-full h-10 bg-bg-primary border border-border-color rounded-xl px-4 pr-10 text-sm font-medium text-text-primary outline-none focus:ring-2 focus:ring-blue-500/20 transition-all appearance-none cursor-pointer">
                                            <option value="idle">Idle (only use I/O when system is free)</option>
                                            <option value="best-effort">Best-effort (normal scheduling)</option>
                                            <option value="realtime">Real-time (highest priority, requires root)</option>
                                        </select>
                                        <ChevronDown size={16} class="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary pointer-events-none" />
                                    </div>
                                    <p class="text-[10px] text-text-secondary leading-tight opacity-60">Applies to scan and backup jobs. Idle is recommended for production systems.</p>
                                </div>
                                <div class="space-y-2">
                                    <label class="text-xs font-medium text-text-secondary ml-1" for="tape-write-strategy">Tape write strategy</label>
                                    <div class="relative">
                                        <select id="tape-write-strategy" bind:value={tapeWriteStrategy} class="w-full h-10 bg-bg-primary border border-border-color rounded-xl px-4 pr-10 text-sm font-medium text-text-primary outline-none focus:ring-2 focus:ring-blue-500/20 transition-all appearance-none cursor-pointer">
                                            <option value="stage">Stage (build tar on disk, then stream to tape — safe, retryable)</option>
                                            <option value="stream">Stream (build tar directly into tape drive — bypasses disk, faster)</option>
                                        </select>
                                        <ChevronDown size={16} class="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary pointer-events-none" />
                                    </div>
                                    <p class="text-[10px] text-text-secondary leading-tight opacity-60">Stream mode requires a fast source disk that can sustain the tape drive's minimum streaming speed to avoid shoe-shining.</p>
                                </div>
                                <div class="space-y-2">
                                    <label class="text-xs font-medium text-text-secondary ml-1" for="redundancy-target">Redundancy target</label>
                                    <input
                                        id="redundancy-target"
                                        type="number"
                                        min="1"
                                        max="10"
                                        bind:value={redundancyTarget}
                                        class="w-full h-10 bg-bg-primary border border-border-color rounded-xl px-4 text-sm font-medium text-text-primary outline-none focus:ring-2 focus:ring-blue-500/20 transition-all"
                                    />
                                    <p class="text-[10px] text-text-secondary leading-tight opacity-60">Number of copies each file should have across active media. Auto-backup cycles through media until this target is met.</p>
                                </div>
                            </div>
                        </Card>

                        <Card class="p-5 shadow-xl">
                            <SectionHeader title="Interface" icon={Monitor} class="mb-6 px-0" />
                            <div class="flex items-center justify-between">
                                <div>
                                    <p class="text-sm font-medium text-text-primary">Support button</p>
                                    <p class="text-[10px] text-text-secondary opacity-60 mt-0.5">Hide the support button</p>
                                </div>
                                <button
                                    onclick={() => showSupportButton.set(!$showSupportButton)}
                                    class="relative w-10 h-6 rounded-full transition-colors {$showSupportButton ? 'bg-blue-600' : 'bg-bg-tertiary border border-border-color'}"
                                    role="switch"
                                    aria-checked={$showSupportButton}
                                >
                                    <span class="block absolute top-1 w-4 h-4 rounded-full bg-white transition-all {$showSupportButton ? 'left-5' : 'left-1'}"></span>
                                </button>
                            </div>
                        </Card>

                        <Card class="p-5 shadow-xl">
                            <SectionHeader title="Index management" icon={Database} class="mb-6 px-0" />
                            <div class="grid grid-cols-2 gap-4">
                                <Button variant="outline" class="h-14 font-medium text-sm group" onclick={handleExport} disabled={exporting}>
                                    {#if exporting}
                                        <RotateCw size={18} class="mr-2 animate-spin" /> Compiling...
                                    {:else}
                                        <Download size={18} class="mr-2 text-blue-400 group-hover:scale-110 transition-transform" /> Export database index
                                    {/if}
                                </Button>
                                <Button variant="outline" class="h-14 font-medium text-sm group opacity-50 cursor-not-allowed">
                                    <Upload size={18} class="mr-2 text-orange-400" /> Import index (Restricted)
                                </Button>
                            </div>
                        </Card>
                    </div>
                {/if}
            {/if}
        </main>
    </div>
</div>
