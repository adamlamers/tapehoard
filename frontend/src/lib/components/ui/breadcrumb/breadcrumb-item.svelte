<script lang="ts">
	import type { HTMLAttributes } from "svelte/elements";
	import { cn } from "$lib/utils";

	let { class: className, children, ...rest }: HTMLAttributes<HTMLLIElement> = $props();
</script>

<li class={cn("inline-flex items-center gap-1.5", className)} {...rest}>
	{@render children?.()}
</li>
