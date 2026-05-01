<script lang="ts">
        import { onMount } from 'svelte';
        import { ChevronRight, Folder, HardDrive } from "lucide-svelte";
        import { RotateCw } from "lucide-svelte";
        import type { TreeNode } from "$lib/types";
        import { cn } from "$lib/utils";
        import FileBrowserTreeItem from "./FileBrowserTreeItem.svelte";
        import { getSystemTreeSystemTreeGet, getArchiveTreeInventoryTreeGet } from "$lib/api";

        let {
                node,
                selectedPath,
                onSelect = (path: string) => {},
                level = 0,
                isSpecial = false,
                mode = "host"
        } = $props<{
                node: TreeNode;
                selectedPath: string | null;
                onSelect?: (path: string) => void;
                level?: number;
                isSpecial?: boolean;
                mode?: "host" | "index" | "live";
        }>();

        let expanded = $state(false);
        let children = $state<TreeNode[]>([]);
        let loading = $state(false);
        let loaded = $state(false);

        // Initialize state from props
        onMount(() => {
                if (node.expanded) {
                    expanded = true;
                }
                if (node.children && node.children.length > 0) {
                    children = node.children;
                    loaded = true;
                }
        });

        // AUTO-EXPAND LOGIC
        $effect(() => {
            if (selectedPath && node.path !== "ROOT") {
                if (selectedPath.startsWith(node.path + "/")) {
                    expanded = true;
                }
            }
        });

        // Auto-load if expanded
        $effect(() => {
                if (expanded && !loaded && !loading) {
                        loadSubdirs();
                }
        });

        async function loadSubdirs() {
                if (loaded || loading) return;

                loading = true;
                try {
                        const fetchFn = (mode === "host" || mode === "live") ? getSystemTreeSystemTreeGet : getArchiveTreeInventoryTreeGet;
                        const response = await fetchFn({
                                query: { path: node.path }
                        });

                        const data = response.data as any[];
                        if (data && Array.isArray(data)) {
                                children = data.map((d: any) => ({
                                        name: d.name,
                                        path: d.path,
                                        children: [],
                                        expanded: false,
                                        hasChildren: d.has_children
                                }));
                        }
                        loaded = true;
                } catch (error) {
                        console.error(`[TreeItem] ${node.path} failed to load subdirectories:`, error);
                        loaded = true;
                } finally {
                        loading = false;
                }
        }

        async function toggle() {
                expanded = !expanded;
        }

        function select() {
                onSelect(node.path);
        }

        const specialIcon = $derived.by(() => {
                if (!isSpecial) return null;
                return HardDrive;
        });

        const hasSubdirs = $derived((children && children.length > 0) || node.hasChildren);
</script>

<div class="tree-item-group">
        <div
                class={cn(
                        "flex items-center gap-1.5 py-1.5 px-3 rounded-lg cursor-pointer group transition-all duration-200",
                        selectedPath === node.path ? "bg-blue-500/20 text-blue-400" : "hover:bg-white/5 text-text-secondary hover:text-text-primary"
                )}
                style="padding-left: {level * 16 + 12}px"
                onclick={select}
                role="treeitem"
                aria-selected={selectedPath === node.path}
                tabindex="0"
                onkeydown={(e) => { if (e.key === 'Enter') select(); }}
        >
                <div class="w-4 h-4 flex items-center justify-center">
                        {#if hasSubdirs}
                                <button
                                        class={cn("p-0.5 rounded hover:bg-white/10 transition-transform duration-300", expanded && "rotate-90")}
                                        onclick={(e) => { e.stopPropagation(); toggle(); }}
                                >
                                        <ChevronRight size={12} />
                                </button>
                        {/if}
                </div>

                <div class="flex items-center gap-2 overflow-hidden">
                        <div class={cn("shrink-0", selectedPath === node.path ? "text-blue-500" : "text-text-secondary/60 group-hover:text-text-secondary")}>
                                {#if specialIcon}
                                        {@const Icon = specialIcon}
                                        <Icon size={14} />
                                {:else}
                                        <Folder size={14} />
                                {/if}
                        </div>
                        <span class="text-[13px] font-medium truncate">
                                {node.name === "ROOT" ? "Virtual Root" : node.name}
                        </span>
                </div>

                {#if loading}
                        <div class="ml-auto">
                                <RotateCw size={10} class="animate-spin opacity-40" />
                        </div>
                {/if}
        </div>

        {#if expanded && children.length > 0}
                <div class="children-container" role="group">
                        {#each children as child}
                                <FileBrowserTreeItem node={child} {selectedPath} {onSelect} level={level + 1} {mode} />
                        {/each}
                </div>
        {/if}
</div>

<style>
        .tree-item-group {
                display: flex;
                flex-direction: column;
        }

        .children-container {
                display: flex;
                flex-direction: column;
        }
</style>
