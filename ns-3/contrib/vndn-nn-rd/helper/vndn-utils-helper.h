/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/**
 * \file vndn-utils-helper.h
 * \brief Shared utilities for VNDN (Vehicular NDN) simulation examples.
 *
 * This helper centralizes the boilerplate code that is duplicated across the
 * ndn4ivc examples (vndn-example-beacon, vndn-example-cbr, vndn-example-tms,
 * ...), so that different simulations can reuse the same code:
 *
 *   - ANSI color codes used for console output
 *   - SUMO scenario name + shell script to count vehicles
 *   - exec() helper to run a shell command and capture its output
 *   - nodesDisable2Move map + checkDisableNodes() periodic callback that
 *     moves "finished" SUMO vehicles out of the communication range
 *
 * Usage from a scratch / example file:
 * \code
 *   #include "ns3/vndn-utils-helper.h"
 *   ...
 *   ns3::ndn::VndnUtilsHelper::ScheduleDisableNodesCheck();
 *   uint32_t nVehicles = std::stoi(ns3::ndn::VndnUtilsHelper::exec(SHELLSCRIPT_NUM_VEHICLES));
 * \endcode
 */

#ifndef VNDN_UTILS_HELPER_H
#define VNDN_UTILS_HELPER_H

#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/mobility-module.h"

#include <string>
#include <map>

namespace ns3 {
namespace ndn {

/** \brief ANSI color escape codes for colored console output.
 *
 * Defined as inline constexpr so they can be used from both headers and
 * translation units without violating the ODR.
 */
#define YELLOW_CODE "\033[33m"
#define RED_CODE "\033[31m"
#define BLUE_CODE "\033[34m"
#define BOLD_CODE "\033[1m"
#define CYAN_CODE "\033[36m"
#define END_CODE "\033[0m"

/** \brief Shared utilities for the VNDN simulation examples.
 *
 * The class only exposes static members: it is a namespace-like aggregator
 * that keeps the global state (nodesDisable2Move) and the helper functions
 * (checkDisableNodes, exec) in a single compilation unit, avoiding the
 * "multiple definition" problems that arise when these symbols are defined
 * in a header included by several examples.
 */
class VndnUtilsHelper
{
public:
  const static std::string ndn4ivc_traces_folder;
  /**
   * \brief Map that records the simulation time at which each node was
   *        "disabled" (its SUMO vehicle finished).
   *
   * It is accessed by checkDisableNodes() and by the shutdown callback of
   * every example. Kept as a public static so the examples can emplace
   * entries exactly as they did before the refactor.
   */
  static std::map<uint32_t, ns3::Time> nodesDisable2Move;

  /**
   * \brief Periodic callback that moves disabled nodes far away from the
   *        scenario (only for visualization purposes) and reschedules itself.
   *
   * This is the function that used to be duplicated as the free function
   * \c checkDisableNodes() in every example file.
   */
  static void
  checkDisableNodes ();

  /**
   * \brief Convenience wrapper that schedules the first invocation of
   *        checkDisableNodes() at t = 1s, starting the self-rescheduling loop.
   */
  static void
  ScheduleDisableNodesCheck ();


  /**
   * \brief Execute a shell command and return its standard output.
   * \param cmd shell command to execute
   * \return the captured stdout of the command
   * \throws std::runtime_error if popen() fails
   *
   * This is the function that used to be duplicated as the free function
   * \c exec() in every example file.
   */
  static std::string
  exec (const std::string&cmd);

  /**
   * \brief Count the number of vehicles defined in a SUMO route file.
   *
   * Builds a shell command that greps the \c vehicle\ id entries from the
   * route file \c <contribFolder>/<scenarioName>/<routeFileName>.rou.xml
   * and returns the number of matches.
   *
   * \param contribFolder path to the contrib module folder (e.g. "contrib/vndn-nn-rd")
   * \param scenarioName  name of the SUMO scenario (sub-folder under traces/)
   * \param routeFileName base name of the route file (without the \c .rou.xml suffix)
   * \return the number of vehicles found in the route file
   *
   * This is the function that used to be the free function
   * \c ShellGetNumOfVehicles() in the ndn4ivc helper, but it now executes the
   * command internally and returns the parsed count directly as a uint32_t.
   */
  static uint32_t
  GetVehicleCount (const std::string &contribFolder, const std::string &scenarioName,
                   const std::string &routeFileName);
};

} // namespace ndn
} // namespace ns3

#endif // VNDN_UTILS_HELPER_H
