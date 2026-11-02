# Day 1 step 11: units built as chains of reaches, scored against the 125 official BC 1:50k Kettle units.
#  Rule S (Strahler stream): a run of equal order >= N is one unit; it ends where the order increases.
#         Reaches below order N join the unit they drain into.
#  Rule A (area chain): at a confluence the larger branch continues the unit; the smaller branch starts a
#         new unit only if it drains >= A km2, otherwise it joins the unit it drains into.
# Inputs: reaches_t{5,10,20}.csv (r.stream.order), units_t{5,10,20}km2.tif (one cell value per reach).
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])); source(file.path(.here, "..", "config.R"))
source(file.path(.here, "..", "scripts", "lib_chain.R"))                       # helpers: load_net, unit_A, unit_S, score
res <- list()
for (NET in c(5,10,20)) { nt <- load_net(NET)
  for (N in 2:4) res[[sprintf("S net%d N%d",NET,N)]] <- score(nt$ras, unit_S(nt,N))
  if (NET %in% c(5,10)) for (A in c(10,20,30,50,80)) res[[sprintf("A net%d A%d",NET,A)]] <- score(nt$ras, unit_A(nt,A))
}
r <- bind_rows(res, .id="set"); r$cls <- cut(r$a_off, c(0,15,30,60,150,2000), labels=c("<15","15-30","30-60","60-150",">150"))
print(n=40, r |> group_by(set) |> summarise(n_units=first(n_der_in), med_iou=round(median(iou),2), ge_0.8=round(mean(iou>=0.8),2), ge_0.5=round(mean(iou>=0.5),2), med_ratio=round(median(a_der/a_off),2)))
write.csv(r, file.path(D, "units_vs_bc50k_chains.csv"), row.names=FALSE)
print(n=80, r |> group_by(set, cls) |> summarise(ge_0.8=round(mean(iou>=0.8),2), .groups="drop") |> tidyr::pivot_wider(names_from=cls, values_from=ge_0.8))
