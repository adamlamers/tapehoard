<script lang="ts">
    import { onMount } from 'svelte';
    import { Search, Save, ShieldAlert, FolderSearch, RotateCw, Plus, Trash2, Download } from 'lucide-svelte';
    import { Button } from '$lib/components/ui/button';
    import { Card } from '$lib/components/ui/card';
    import { Input } from '$lib/components/ui/input';
    import { getSettingsSystemSettingsGet, updateSettingSystemSettingsPost } from '$lib/api/sdk.gen';
    import { toast } from "svelte-sonner";

    let sourceRoots = $state<string[]>(["/source_data"]);
    let restoreDestinations = $state<string[]>(["/restores"]);
    let globalExclusions = $state("*.tmp\nnode_modules/\n.DS_Store\nThumbs.db\nCache/\n");
    let loading = $state(true);
    let saving = $state(false);

    async function loadSettings() {
        loading = true;
        try {
            const response = await getSettingsSystemSettingsGet();
            if (response.data) {
                if (response.data.source_roots) {
                    try { sourceRoots = JSON.parse(response.data.source_roots); } catch { sourceRoots = [response.data.source_roots]; }
                }
                if (response.data.restore_destinations) {
                    try { restoreDestinations = JSON.parse(response.data.restore_destinations); } catch { restoreDestinations = [response.data.restore_destinations]; }
                }
                if (response.data.global_exclusions) {
                    globalExclusions = response.data.global_exclusions;
                }
            }
        } catch (error) {
            console.error("Failed to load settings:", error);
            toast.error("Failed to load system settings");
        } finally {
            loading = false;
        }
    }

    onMount(loadSettings);

    function addSourceRoot() { sourceRoots = [...sourceRoots, ""]; }
    function removeSourceRoot(index: number) { sourceRoots = sourceRoots.filter((_, i) => i !== index); }

    function addRestoreDest() { restoreDestinations = [...restoreDestinations, ""]; }
    function removeRestoreDest(index: number) { restoreDestinations = restoreDestinations.filter((_, i) => i !== index); }

    async function saveSettings() {
        saving = true;
        try {
            const roots = sourceRoots.filter(r => r.trim() !== "");
            const dests = restoreDestinations.filter(d => d.trim() !== "");

            await Promise.all([
                updateSettingSystemSettingsPost({ body: { key: "source_roots", value: JSON.stringify(roots) } }),
                updateSettingSystemSettingsPost({ body: { key: "restore_destinations", value: JSON.stringify(dests) } }),
                updateSettingSystemSettingsPost({ body: { key: "global_exclusions", value: globalExclusions } })
            ]);

            toast.success("Settings saved successfully");
            sourceRoots = roots;
            restoreDestinations = dests;
        } catch (error) {
            toast.error("Failed to save settings");
        } finally {
            saving = false;
        }
    }
</script>

<svelte:head>
    <title>Settings - TapeHoard</title>
</svelte:head>

<div class="flex justify-between items-center mb-8 bg-bg-secondary p-6 rounded-xl border border-border-color shadow-lg relative overflow-hidden">
    <div class="absolute inset-0 bg-gradient-to-r from-action-color/5 to-transparent pointer-events-none"></div>
    <div class="relative z-10">
        <h1 class="text-3xl font-black uppercase tracking-tighter text-text-primary">System Settings</h1>
        <p class="text-text-secondary mt-1 font-bold uppercase tracking-widest text-[10px] opacity-70">Global Backup Configuration & Policy Engine</p>
    </div>
    <div class="flex gap-4 relative z-10">
        <Button variant="default" size="lg" class="px-8 h-12 font-black uppercase tracking-widest text-[11px]" onclick={saveSettings} disabled={saving}>
            {#if saving}
                <RotateCw size={20} class="mr-2 animate-spin" />
            {:else}
                <Save size={20} class="mr-2" />
            {/if}
            Apply Settings
        </Button>
    </div>
</div>

{#if loading}
    <div class="flex flex-col items-center justify-center py-24 gap-4 opacity-50">
        <RotateCw size={48} class="animate-spin text-action-color" />
        <span class="text-xs font-black uppercase tracking-widest">Hydrating Configuration...</span>
    </div>
{:else}
    <div class="max-w-4xl mx-auto space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-700">
        <!-- Source Configuration -->
        <Card class="p-8 shadow-xl border-border-color/60 bg-gradient-to-br from-bg-secondary to-bg-tertiary">
            <div class="flex items-center justify-between mb-6">
                <div class="flex items-center gap-3">
                    <div class="p-2 bg-blue-500/10 rounded-lg text-blue-500 border border-blue-500/20"><FolderSearch size={24} /></div>
                    <div><h3 class="text-lg font-black text-text-primary uppercase tracking-tight">Source Provisioning</h3><p class="text-[11px] text-text-secondary font-medium uppercase tracking-wider opacity-60">Primary data ingestion points.</p></div>
                </div>
                <Button variant="secondary" size="sm" class="h-8 uppercase tracking-widest text-[10px] font-bold" onclick={addSourceRoot}><Plus size={14} class="mr-1" /> Add Source</Button>
            </div>
            <div class="space-y-4">
                {#each sourceRoots as root, i}
                    <div class="flex gap-2">
                        <Input bind:value={sourceRoots[i]} class="h-11 bg-bg-primary/50 border-border-color font-mono text-[13px]" placeholder="/path/to/data" />
                        <Button variant="ghost" size="icon" class="h-11 w-11 text-text-secondary hover:text-error-color hover:bg-error-color/10" onclick={() => removeSourceRoot(i)}><Trash2 size={18} /></Button>
                    </div>
                {/each}
            </div>
        </Card>

        <!-- Restore Destinations -->
        <Card class="p-8 shadow-xl border-border-color/60 bg-gradient-to-br from-bg-secondary to-bg-tertiary">
            <div class="flex items-center justify-between mb-6">
                <div class="flex items-center gap-3">
                    <div class="p-2 bg-success-color/10 rounded-lg text-success-color border border-success-color/20"><Download size={24} /></div>
                    <div><h3 class="text-lg font-black text-text-primary uppercase tracking-tight">Recovery Targets</h3><p class="text-[11px] text-text-secondary font-medium uppercase tracking-wider opacity-60">Authorized destinations for restored data.</p></div>
                </div>
                <Button variant="secondary" size="sm" class="h-8 uppercase tracking-widest text-[10px] font-bold" onclick={addRestoreDest}><Plus size={14} class="mr-1" /> Add Target</Button>
            </div>
            <div class="space-y-4">
                {#each restoreDestinations as dest, i}
                    <div class="flex gap-2">
                        <Input bind:value={restoreDestinations[i]} class="h-11 bg-bg-primary/50 border-border-color font-mono text-[13px]" placeholder="/path/to/restores" />
                        <Button variant="ghost" size="icon" class="h-11 w-11 text-text-secondary hover:text-error-color hover:bg-error-color/10" onclick={() => removeRestoreDest(i)}><Trash2 size={18} /></Button>
                    </div>
                {/each}
            </div>
        </Card>

        <!-- Exclusion Engine -->
        <Card class="p-8 shadow-xl border-border-color/60 bg-gradient-to-br from-bg-secondary to-bg-tertiary">
            <div class="flex items-center justify-between mb-6">
                <div class="flex items-center gap-3">
                    <div class="p-2 bg-action-color/10 rounded-lg text-action-color border border-action-color/20"><Search size={24} /></div>
                    <div><h3 class="text-lg font-black text-text-primary uppercase tracking-tight">Exclusion Engine</h3><p class="text-[11px] text-text-secondary font-medium uppercase tracking-wider opacity-60">Patterns to bypass during scans.</p></div>
                </div>
                <span class="text-[10px] font-black tracking-widest text-text-secondary bg-bg-primary px-3 py-1 rounded-full border border-border-color uppercase">.gitignore syntax</span>
            </div>
            <textarea bind:value={globalExclusions} class="w-full h-48 bg-bg-primary/50 border border-border-color rounded-lg p-6 text-[14px] mono text-text-primary focus:ring-1 focus:ring-action-color focus:outline-none resize-none leading-relaxed transition-all shadow-inner" placeholder="e.g. *.tmp"></textarea>
            <div class="mt-6 p-4 bg-orange-500/5 border border-dashed border-orange-500/30 rounded-lg flex gap-4 items-start">
                <ShieldAlert size={20} class="text-orange-500 shrink-0 mt-0.5" />
                <p class="text-[12px] text-text-secondary leading-normal font-medium"><strong class="text-orange-500 uppercase tracking-tight text-[11px] block mb-1">Warning</strong>Broad exclusion patterns can result in incomplete backups.</p>
            </div>
        </Card>
    </div>
{/if}
