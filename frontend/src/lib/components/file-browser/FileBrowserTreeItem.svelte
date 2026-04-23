<script lang="ts">
        import { ChevronRight, Folder, Home, HardDrive, Monitor, Download, FileText, Image } from "lucide-svelte";
        import type { TreeNode } from "$lib/types";
        import { cn } from "$lib/utils";
        import FileBrowserTreeItem from "./FileBrowserTreeItem.svelte";
        import { getTreeSystemTreeGet } from "$lib/api/sdk.gen";

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

        let expanded = $state(node.expanded || false);
        let children = $state<TreeNode[]>(node.children || []);
        let loading = $state(false);
        let loaded = $state(false);

        // Auto-load if started expanded
        $effect(() => {
                if (expanded && !loaded) {
                        loadSubdirs();
                }
        });

        async function loadSubdirs() {
                if (loaded || mode === "index") return; // Index mode lazy loading not yet implemented

                loading = true;
                try {
                        const response = await getTreeSystemTreeGet({
                                query: { path: node.path }
                        });
                        if (response.data) {
                                children = response.data.map(d => ({
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
                if (expanded && !loaded) {
                        await loadSubdirs();
                }
        }

        function select() {
                onSelect(node.path);
        }

        const specialIcon = $derived.by(() => {
                if (!isSpecial) return null;
                switch (node.name.toLowerCase()) {
                        case "source data":
                        case "this pc":
                        case "root":
                        case "virtual index":
                                return HardDrive;
                        default:
                                return HardDrive;
                }
        });

        const hasSubdirs = $derived((children && children.length > 0) || (node as any).hasChildren);

        function handleKeyDown(e: KeyboardEvent) {
                if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        select();
                } else if (e.key === "ArrowRight") {
                        if (!expanded) toggle();
                } else if (e.key === "ArrowLeft") {
                        if (expanded) toggle();
                }
        }
</script>

<div class="tree-item-group">
        <div
                class={cn(
                        "group flex items-center gap-2 py-1.5 px-3 cursor-pointer select-none transition-all rounded-sm",
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
</style>
