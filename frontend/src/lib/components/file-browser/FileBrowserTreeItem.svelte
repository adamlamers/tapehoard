<script lang="ts">
        import { onMount } from 'svelte';
        import { ChevronRight, Folder, HardDrive } from "lucide-svelte";
        import type { TreeNode } from "$lib/types";
        import { cn } from "$lib/utils";
        import FileBrowserTreeItem from "./FileBrowserTreeItem.svelte";
        import { getSystemTreeSystemTreeGet, getArchiveTreeInventoryTreeGet, type TreeNodeSchema } from "$lib/api";

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
                mode?: "host" | "index";
        }>();

        let expanded = $state(false);
        let children = $state<TreeNode[]>([]);
        let loading = $state(false);
        let loaded = $state(false);

        // Initialize state from props
        onMount(() => {
                if (node.expanded) expanded = true;
                if (node.children && node.children.length > 0) {
                    children = node.children;
                    loaded = true;
                }
        });

        // AUTO-EXPAND LOGIC:
        // If the current global path is a child of this node, we should expand to show it.
        $effect(() => {
            if (selectedPath && node.path !== "ROOT") {
                // If selectedPath starts with node.path, we are a parent of the active view
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
                if (loaded) return;

                loading = true;
                try {
                        const fetchFn = mode === "host" ? getSystemTreeSystemTreeGet : getArchiveTreeInventoryTreeGet;
                        const response = await fetchFn({
                                query: { path: node.path }
                        });

                        const data = response.data as TreeNodeSchema[];

                        if (data && Array.isArray(data)) {
                                children = data.map((d: TreeNodeSchema) => ({
                                        name: d.name,
                                        path: d.path,
                                        children: [],
                                        expanded: false,
                                        hasChildren: d.has_children
                                }));
                                loaded = true;
                        }
                } catch (error) {
                        console.error("Failed to load subdirectories:", error);
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

        function handleKeyDown(e: KeyboardEvent) {
                if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        select();
                } else if (e.key === "ArrowRight") {
                        if (!expanded) expanded = true;
                } else if (e.key === "ArrowLeft") {
                        if (expanded) expanded = false;
                }
        }
</script>

<div class="tree-item-group">
        <div
                class={cn(
                        "group flex items-center gap-2 py-1.5 px-3 cursor-pointer select-none transition-all rounded-sm outline-none focus:ring-1 focus:ring-blue-500/30",
                        selectedPath === node.path
                                ? "bg-blue-500/15 text-text-primary shadow-sm border-l-2 border-blue-500"
                                : "text-text-secondary hover:bg-white/5 hover:text-text-primary border-l-2 border-transparent"
                )}
                style="padding-left: {level * 12 + (isSpecial ? 12 : 8)}px"
                onclick={select}
                onkeydown={handleKeyDown}
                role="treeitem"
                aria-selected={selectedPath === node.path}
                aria-expanded={hasSubdirs ? expanded : undefined}
                tabindex="0"
        >
                <!-- EXPANDER ARROW -->
                <button
                        class={cn(
                                "w-4 h-4 flex items-center justify-center transition-all",
                                hasSubdirs ? "opacity-60 hover:opacity-100" : "opacity-0 pointer-events-none"
                        )}
                        onclick={(e) => {
                                e.stopPropagation();
                                toggle();
                        }}
                        tabindex="-1"
                >
                        <ChevronRight
                                size={12}
                                strokeWidth={3}
                                class={cn("transition-transform duration-200", expanded && "rotate-90", loading && "animate-pulse")}
                        ></ChevronRight>
                </button>

                <!-- ICON -->
                {#if isSpecial && specialIcon}
                        {@const Icon = specialIcon}
                        <Icon
                                size={16}
                                class={cn(
                                        "shrink-0 transition-colors",
                                        selectedPath === node.path ? "text-blue-400" : "text-text-secondary/60 group-hover:text-text-secondary/90"
                                )}
                        ></Icon>
                {:else}
                        <Folder
                                size={16}
                                class={cn(
                                        "shrink-0 transition-colors",
                                        selectedPath === node.path
                                                ? "text-yellow-500/80 fill-yellow-500/10"
                                                : "text-text-secondary/40 group-hover:text-text-secondary/80"
                                )}
                        ></Folder>
                {/if}

                <!-- LABEL -->
                <span class={cn("text-[13px] truncate", selectedPath === node.path ? "font-semibold" : "font-medium")}>
                        {node.name}
                </span>
        </div>

        {#if expanded && children.length > 0}
                <div role="group">
                        {#each children as child (child.path)}
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
</style>
