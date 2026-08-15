/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/**
 * \file vndn-utils-helper.cc
 * \brief Implementation of the shared VNDN utilities (see vndn-utils-helper.h).
 */

#include "ns3/vndn-utils-helper.h"

#include <rapidxml.hpp>

#include <array>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <memory>
#include <stdexcept>
#include <vector>

namespace ns3 {
namespace ndn {

// definition of the static data member declared in the header
std::map<uint32_t, ns3::Time> VndnUtilsHelper::nodesDisable2Move;
const std::string VndnUtilsHelper::ndn4ivc_traces_folder = "contrib/vndn-nn-rd/traces";
void
VndnUtilsHelper::checkDisableNodes ()
{
  for (auto it = nodesDisable2Move.begin (), it_next = it; it != nodesDisable2Move.end ();
       it = it_next)
    {
      ++it_next;
      Ptr<Node> exNode = ns3::NodeList::GetNode (it->first);
      // NOTE:we'll put the node in a new position, outside the simulation
      // communication range, but this is just for better visualization mode
      if ((ns3::Time) ns3::Simulator::Now ().GetSeconds () - it->second > 1)
        {
          Ptr<ConstantPositionMobilityModel> mob =
              exNode->GetObject<ConstantPositionMobilityModel> ();
          mob->SetPosition (Vector ((double) exNode->GetId (), -4000 - (rand () % 25), -5000.0));
          nodesDisable2Move.erase (it);
        }
    }
  Simulator::Schedule (Seconds (1), &VndnUtilsHelper::checkDisableNodes);
}

void
VndnUtilsHelper::ScheduleDisableNodesCheck ()
{
  Simulator::Schedule (Seconds (1), &VndnUtilsHelper::checkDisableNodes);
}

std::string
VndnUtilsHelper::exec (const std::string &cmd)
{
  std::array<char, 128> buffer;
  std::string result;
  std::unique_ptr<FILE, decltype (&pclose)> pipe (popen (cmd.c_str(), "r"), pclose);
  if (!pipe)
    throw std::runtime_error ("exec failed!");
  while (fgets (buffer.data (), buffer.size (), pipe.get ()) != nullptr)
    result += buffer.data ();
  return result;
}

uint32_t
VndnUtilsHelper::GetVehicleCount (const std::string &contribFolder, const std::string &scenarioName,
                                  const std::string &routeFileName)
{
  // Build the path to the SUMO route file:
  // <contribFolder>/traces/<scenarioName>/<routeFileName>.rou.xml
  std::string filePath = contribFolder + "/./" + scenarioName + "/" +
                         routeFileName + ".rou.xml";

  // Read the whole XML file into a buffer (rapidxml requires a mutable,
  // null-terminated buffer).
  std::ifstream theFile (filePath);
  if (!theFile.is_open ())
    {
      std::cerr << "VndnUtilsHelper::GetVehicleCount: cannot open " << filePath << std::endl;
      return 0;
    }
  std::vector<char> buffer ((std::istreambuf_iterator<char> (theFile)),
                            std::istreambuf_iterator<char> ());
  buffer.push_back ('\0');

  // Parse the buffer and count the <vehicle> nodes.
  rapidxml::xml_document<> doc;
  doc.parse<0> (&buffer[0]);
  rapidxml::xml_node<> *root_node = doc.first_node ("routes");
  if (!root_node)
    return 0;

  uint32_t count = 0;
  for (rapidxml::xml_node<> *vehicle_node = root_node->first_node ("vehicle"); vehicle_node;
       vehicle_node = vehicle_node->next_sibling ("vehicle"))
    {
      count++;
    }
  return count;
}

std::vector<ns3::Vector>
VndnUtilsHelper::GetRsuLocations (const std::string &contribFolder,
                                  const std::string &scenarioName,
                                  const std::string &settingsFileName)
{
  const std::string filePath =
      contribFolder + "/" + scenarioName + "/" + settingsFileName;
  std::ifstream settingsFile (filePath);
  if (!settingsFile.is_open ())
    {
      std::cerr << "VndnUtilsHelper::GetRsuLocations: cannot open " << filePath
                << std::endl;
      return {};
    }

  // rapidxml 会直接修改输入缓冲区，所以必须保留一个可写且以 '\0' 结尾的副本。
  // rapidxml parses in place; keep a writable, null-terminated copy of the file.
  std::vector<char> buffer ((std::istreambuf_iterator<char> (settingsFile)),
                            std::istreambuf_iterator<char> ());
  buffer.push_back ('\0');

  std::vector<ns3::Vector> locations;
  try
    {
      rapidxml::xml_document<> document;
      document.parse<0> (buffer.data ());
      rapidxml::xml_node<> *viewSettings = document.first_node ("viewsettings");
      rapidxml::xml_node<> *decals =
          viewSettings == nullptr ? nullptr : viewSettings->first_node ("decals");
      if (decals == nullptr)
        {
          std::cerr << "VndnUtilsHelper::GetRsuLocations: no <decals> in "
                    << filePath << std::endl;
          return {};
        }

      for (rapidxml::xml_node<> *decal = decals->first_node ("decal"); decal != nullptr;
           decal = decal->next_sibling ("decal"))
        {
          rapidxml::xml_attribute<> *type = decal->first_attribute ("type");
          if (type == nullptr || std::string (type->value ()) != "rsu")
            continue;

          rapidxml::xml_attribute<> *centerX = decal->first_attribute ("centerX");
          rapidxml::xml_attribute<> *centerY = decal->first_attribute ("centerY");
          if (centerX == nullptr || centerY == nullptr)
            {
              std::cerr << "VndnUtilsHelper::GetRsuLocations: RSU decal misses centerX/centerY in "
                        << filePath << std::endl;
              continue;
            }

          // settings.xml 里的 centerZ 是 SUMO GUI 图片高度，并不可靠（旧 grid
          // 的第三个 RSU 甚至写成了 120）。旧仿真安装无线节点时统一使用 12 m，
          // 新场景也保持这一物理高度，避免 GUI 元数据意外改变无线覆盖。
          const double z = 12.0;
          locations.emplace_back (std::stod (centerX->value ()),
                                  std::stod (centerY->value ()), z);
        }
    }
  catch (const rapidxml::parse_error &error)
    {
      std::cerr << "VndnUtilsHelper::GetRsuLocations: invalid XML in " << filePath
                << ": " << error.what () << std::endl;
      return {};
    }
  catch (const std::exception &error)
    {
      std::cerr << "VndnUtilsHelper::GetRsuLocations: invalid RSU coordinate in "
                << filePath << ": " << error.what () << std::endl;
      return {};
    }
  return locations;
}

bool
VndnUtilsHelper::SaveSimulationConfig (
    const std::string &outputDir,
    const std::vector<std::pair<std::string, std::string>> &parameters,
    const std::string &fileName)
{
  std::string filePath = outputDir;
  if (!filePath.empty () && filePath.back () != '/')
    filePath += '/';
  filePath += fileName;

  std::ofstream file (filePath, std::ios::out | std::ios::trunc);
  if (!file.is_open ())
    return false;

  for (const auto &parameter : parameters)
    file << parameter.first << '=' << parameter.second << '\n';
  return file.good ();
}

} // namespace ndn
} // namespace ns3
