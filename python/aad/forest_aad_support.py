import os
import numpy as np
import matplotlib.pyplot as plt

import logging
from pandas import DataFrame

from aad.aad_globals import *
from aad.aad_support import *

from forest_aad_detector import *
from common.data_plotter import *


def forest_aad_unit_tests_battery(X_train, labels, model, metrics, opts,
                                  outputdir, dataset_name=""):

    data_2D = X_train.shape[1] == 2

    regcols = ["red", "blue", "green", "brown", "cyan", "pink", "orange", "magenta", "yellow", "violet"]

    xx = None; yy = None
    if data_2D:
        # plot the line, the samples, and the nearest vectors to the plane
        xx, yy = np.meshgrid(np.linspace(-4, 8, 50), np.linspace(-4, 8, 50))

    # sidebar coordinates and dimensions for showing rank locations of true anomalies
    dash_xy = (-4.0, -2.0)  # bottom-left (x,y) coordinates
    dash_wh = (0.4, 8)  # width, height

    output_forest_original = False
    output_transformed_to_file = False
    test_loss_grad = False
    plot_dataset = data_2D and True
    plot_rectangular_regions = plot_dataset and True
    plot_forest_contours = data_2D and True
    plot_baseline = data_2D and False
    plot_aad = metrics is not None and data_2D and True

    pdfpath_baseline = "%s/tree_baseline.pdf" % outputdir
    pdfpath_orig_if_contours = "%s/score_contours.pdf" % outputdir

    logger.debug("Number of regions: %d" % len(model.d))

    tm = Timer()
    X_train_new = model.transform_to_region_features(X_train, dense=False, norm_unit=opts.norm_unit)
    logger.debug(tm.message("transformed input to region features"))

    if plot_dataset:
        tm.start()
        plot_dataset_2D(X_train, labels, model, plot_rectangular_regions, regcols, outputdir)
        logger.debug(tm.message("plotted dataset"))

    if output_forest_original:
        n_found = evaluate_forest_original(X_train, labels, opts.budget, model, x_new=X_train_new)
        np.savetxt(os.path.join(outputdir, "iforest_original_num_found_%s.csv" % dataset_name),
                   n_found, fmt='%3.2f', delimiter=",")

    if plot_forest_contours:
        tm.start()
        plot_forest_contours_2D(X_train, labels, xx, yy, opts.budget, model,
                                pdfpath_orig_if_contours, dash_xy, dash_wh)
        logger.debug(tm.message("plotted contours"))

    if output_transformed_to_file:
        write_sparsemat_to_file(os.path.join(outputdir, "forest_features.csv"),
                                X_train_new, fmt='%3.2f', delimiter=",")
        x_tmp = np.vstack((model.d, model.node_samples, model.frac_insts))
        write_sparsemat_to_file(os.path.join(outputdir, "forest_node_info.csv"),
                                x_tmp.T, fmt='%3.2f', delimiter=",")

    if plot_baseline:
        plot_forest_baseline_contours_2D(X_train, labels, X_train_new, xx, yy, opts.budget, model,
                                         pdfpath_baseline, dash_xy, dash_wh, opts)

    if plot_aad and metrics is not None:
        plot_aad_2D(X_train, labels, X_train_new, xx, yy, model,
                    metrics, outputdir, dash_xy, dash_wh, opts)


def check_random_vector_angle(model, vec, samples=None):
    tmp = np.zeros(200, dtype=float)
    for i in range(len(tmp)):
        rndw = model.get_random_weights(samples=samples)
        cos_theta = vec.dot(rndw)
        tmp[i] = np.arccos(cos_theta) * 180. / np.pi
    logger.debug("random vector angles:\n%s" % (str(list(tmp))))


def plot_qval_hist(qfirst, qlast, i, outputdir):
    pdfpath = "%s/qval_hist_%d.pdf" % (outputdir, i)
    dp = DataPlotter(pdfpath=pdfpath, rows=1, cols=1)
    qall = np.append(qfirst, qlast)
    bins = np.arange(start=np.min(qall), stop=np.max(qall), step=(np.max(qall)-np.min(qall))/50)
    pl = dp.get_next_plot()
    n1, bins1 = np.histogram(qfirst, bins=bins, normed=True)
    n2, bins2 = np.histogram(qlast, bins=bins, normed=True)
    width = 0.7 * (bins[1] - bins[0])
    center = (bins[:-1] + bins[1:]) / 2
    plt.bar(center, n1, align='center', width=width, facecolor='green', alpha=0.50)
    plt.bar(center, n2, align='center', width=width, facecolor='red', alpha=0.50)
    dp.close()


def debug_qvals(samples, model, metrics, outputdir, opts):
    n = samples.shape[0]
    bt = get_budget_topK(n, opts)
    unif_w = model.get_uniform_weights()
    budget = metrics.all_weights.shape[0]
    if budget > 1:
        plot_qval_hist(metrics.all_weights[0], metrics.all_weights[budget-1], opts.runidx, outputdir)
    for i in range(metrics.all_weights.shape[0]):
        w = metrics.all_weights[i]
        s = samples.dot(w)
        qval = quantile(s, (1.0 - (bt.topK * 1.0 / float(n))) * 100.0)
        qmin = np.min(s)
        qmax = np.max(s)
        cos_theta = max(-1.0, min(1.0, unif_w.dot(w)))
        # logger.debug("cos_theta: %f" % cos_theta)
        angle = np.arccos(cos_theta) * 180. / np.pi
        logger.debug("[%d] qval: %1.6f [%1.6f, %1.6f]; angle: %2.6f" % (i, qval, qmin, qmax, angle))
    est_qval, est_qmin, est_qmax = estimate_qtau(samples, model, opts, lo=0.0, hi=1.0)
    logger.debug("[%d] estimated qval (0, 1): %1.6f [%1.6f, %1.6f]" % (opts.runidx, est_qval, est_qmin, est_qmax))
    est_qval, est_qmin, est_qmax = estimate_qtau(samples, model, opts, lo=-1.0, hi=1.0)
    logger.debug("[%d] estimated qval (-1,1): %1.6f [%1.6f, %1.6f]" % (opts.runidx, est_qval, est_qmin, est_qmax))


def plot_aad_2D(x, y, x_forest, xx, yy, forest, metrics,
                outputdir, dash_xy, dash_wh, opts):
    # use this to plot the AAD feedback

    x_test = np.c_[xx.ravel(), yy.ravel()]
    x_if = forest.transform_to_region_features(x_test, dense=False, norm_unit=opts.norm_unit)

    queried = np.array(metrics.queried)
    for i, q in enumerate(queried):
        pdfpath = "%s/iter_%02d.pdf" % (outputdir, i)
        dp = DataPlotter(pdfpath=pdfpath, rows=1, cols=1)
        pl = dp.get_next_plot()

        w = metrics.all_weights[i, :]
        Z = forest.get_score(x_if, w)
        Z = Z.reshape(xx.shape)

        pl.contourf(xx, yy, Z, 20, cmap=plt.cm.get_cmap('jet'))

        dp.plot_points(x, pl, labels=y, lbl_color_map={0: "grey", 1: "red"}, s=25)
        # print queried[np.arange(i+1)]
        # print X_train[queried[np.arange(i+1)], :]
        dp.plot_points(matrix(x[queried[np.arange(i+1)], :], nrow=i+1),
                       pl, labels=y[queried[np.arange(i+1)]], defaultcol="red",
                       lbl_color_map={0: "green", 1: "red"}, edgecolor=None, facecolors=True,
                       marker=matplotlib.markers.MarkerStyle('o', fillstyle=None), s=35)

        # plot the sidebar
        anom_scores = forest.get_score(x_forest, w)
        anom_order = np.argsort(-anom_scores)
        anom_idxs = np.where(y[anom_order] == 1)[0]
        dash = 1 - (anom_idxs * 1.0 / x.shape[0])
        plot_sidebar(dash, dash_xy, dash_wh, pl)

        dp.close()


def evaluate_forest_original(x, y, budget, forest, x_new=None):
    original_scores = 0.5 - forest.decision_function(x)
    queried = np.argsort(-original_scores)

    n_found_orig = np.cumsum(y[queried[np.arange(budget)]])
    # logger.debug("original isolation forest:")
    # logger.debug(n_found_orig)

    if x_new is not None:
        w = np.ones(len(forest.d), dtype=float)
        w = w / w.dot(w)  # normalized uniform weights
        agg_scores = forest.get_score(x_new, w)
        queried = np.argsort(-agg_scores)
        n_found_baseline = np.cumsum(y[queried[np.arange(budget)]])
        n_found = np.vstack((n_found_baseline, n_found_orig)).T
    else:
        n_found = np.reshape(n_found_orig, (1, len(n_found_orig)))
    return n_found


def plot_forest_baseline_contours_2D(x, y, x_forest, xx, yy, budget, forest,
                                     pdfpath_contours, dash_xy, dash_wh, opts):
    # use this to plot baseline query points.

    w = np.ones(len(forest.d), dtype=float)
    w = w / w.dot(w)  # normalized uniform weights

    baseline_scores = forest.get_score(x_forest, w)
    queried = np.argsort(-baseline_scores)

    n_found = np.cumsum(y[queried[np.arange(budget)]])
    print n_found

    dp = DataPlotter(pdfpath=pdfpath_contours, rows=1, cols=1)
    pl = dp.get_next_plot()

    x_test = np.c_[xx.ravel(), yy.ravel()]
    x_if = forest.transform_to_region_features(x_test, dense=False, norm_unit=opts.norm_unit)
    y_if = forest.get_score(x_if, w)
    Z = y_if.reshape(xx.shape)

    pl.contourf(xx, yy, Z, 20, cmap=plt.cm.get_cmap('jet'))

    dp.plot_points(x, pl, labels=y, lbl_color_map={0: "grey", 1: "red"}, s=25)
    # print queried[np.arange(i+1)]
    # print X_train[queried[np.arange(i+1)], :]
    dp.plot_points(matrix(x[queried[np.arange(budget)], :], nrow=budget),
                   pl, labels=y[queried[np.arange(budget)]], defaultcol="red",
                   lbl_color_map={0: "green", 1: "red"}, edgecolor="black",
                   marker=matplotlib.markers.MarkerStyle('o', fillstyle=None), s=35)

    # plot the sidebar
    anom_idxs = np.where(y[queried] == 1)[0]
    dash = 1 - (anom_idxs * 1.0 / x.shape[0])
    plot_sidebar(dash, dash_xy, dash_wh, pl)

    dp.close()


def plot_forest_contours_2D(x, y, xx, yy, budget, forest, pdfpath_contours, dash_xy, dash_wh):
    # Original detector contours
    baseline_scores = 0.5 - forest.decision_function(x)
    queried = np.argsort(-baseline_scores)
    # logger.debug("baseline scores:%s\n%s" % (str(baseline_scores.shape), str(list(baseline_scores))))

    n_found = np.cumsum(y[queried[np.arange(budget)]])
    print n_found

    Z_if = 0.5 - forest.decision_function(np.c_[xx.ravel(), yy.ravel()])
    Z_if = Z_if.reshape(xx.shape)

    dp = DataPlotter(pdfpath=pdfpath_contours, rows=1, cols=1)
    pl = dp.get_next_plot()
    pl.contourf(xx, yy, Z_if, 20, cmap=plt.cm.get_cmap('jet'))

    dp.plot_points(x, pl, labels=y, lbl_color_map={0: "grey", 1: "red"})

    dp.plot_points(matrix(x[queried[np.arange(budget)], :], nrow=budget),
                   pl, labels=y[queried[np.arange(budget)]], defaultcol="red",
                   lbl_color_map={0: "green", 1: "red"}, edgecolor="black",
                   marker=matplotlib.markers.MarkerStyle('o', fillstyle=None), s=35)

    # plot the sidebar
    anom_idxs = np.where(y[queried] == 1)[0]
    dash = 1 - (anom_idxs * 1.0 / x.shape[0])
    plot_sidebar(dash, dash_xy, dash_wh, pl)

    dp.close()


def plot_dataset_2D(x, y, forest, plot_regions, regcols, pdf_folder):
    # use this to plot the dataset

    treesig = "_%d_trees" % forest.n_estimators if plot_regions else ""
    pdfpath_dataset = "%s/synth_dataset%s.pdf" % (pdf_folder, treesig)
    dp = DataPlotter(pdfpath=pdfpath_dataset, rows=1, cols=1)
    pl = dp.get_next_plot()

    # dp.plot_points(x, pl, labels=y, lbl_color_map={0: "grey", 1: "red"})
    dp.plot_points(x[y==0, :], pl, labels=y[y==0], defaultcol="grey")
    dp.plot_points(x[y==1, :], pl, labels=y[y==1], defaultcol="red", s=26, linewidths=1.5)

    if plot_regions:
        # plot the isolation forest tree regions
        axis_lims = (plt.xlim(), plt.ylim())
        for i, regions in enumerate(forest.regions_in_forest):
            for region in regions:
                region = region.region
                plot_rect_region(pl, region, regcols[i % len(regcols)], axis_lims)
    dp.close()